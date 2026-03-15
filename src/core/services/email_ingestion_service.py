"""
core/services/email_ingest_service.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Routes a parsed inbound EmailPayload to one of two paths:

NEW TICKET
──────────
  No matching ticket found → call TicketService.create_ticket()
  (runs the full pipeline: classify → SLA → ACKNOWLEDGED → auto-assign)
  and save an EmailThread row linking this email to the new ticket.

REPLY (add comment)
───────────────────
  Matching ticket found → add a TicketComment with the email body
  and save a new EmailThread row linked to the same ticket.

Thread matching priority
────────────────────────
  1. In-Reply-To header   → look up stored EmailThread by that message_id
  2. References chain     → walk oldest-first, same lookup
  3. [TKT-XXXX] in subject → direct ticket_number lookup

Idempotency
───────────
  message_id unique constraint + get_by_message_id() check at the top.
  Safe to call multiple times for the same email (e.g. after a crash).

Customer resolution
───────────────────
  Looks up the sender by email via Auth Service.
  If not found, provisions a basic customer account automatically.
  This keeps the ingest pipeline fully autonomous — no manual user creation needed.

Error handling
──────────────
  Any exception is caught, logged, and a failed EmailThread row is written
  with ticket_id=NULL so failures are visible in the DB and can be retried.
  The exception is then re-raised so the Celery task can decide on retry.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.constants.enum import Environment, TicketSource, UserRole
from src.core.services.notification.manager import notification_manager
from src.core.services.ticket_service import TicketService
from src.data.clients.auth_client import AuthServiceClient, UserDTO
from src.data.clients.postgres_client import AsyncSessionFactory
from src.data.models.postgres.email_thread import EmailDirection, EmailThread
from src.data.models.postgres.ticket_comment import TicketComment
from src.data.repositories.area_of_concern_repository import AreaOfConcernRepository
from src.data.repositories.email_thread_repository import EmailThreadRepository
from src.data.repositories.ticket_comment_repository import TicketCommentRepository
from src.data.repositories.ticket_repository import TicketRepository
from src.schemas.email_schema import EmailPayload
from src.schemas.notification_schema import TicketCreatedRequest
from src.schemas.ticket_schema import TicketCreateRequest

logger = logging.getLogger(__name__)

_TICKET_NUM_RE = re.compile(r"\[TKT-(\d+)\]", re.IGNORECASE)


class EmailIngestService:

    def __init__(self, db: AsyncSession, auth_client: AuthServiceClient) -> None:
        self._db = db
        self._auth = auth_client
        self._thread_repo = EmailThreadRepository(db)
        self._ticket_repo = TicketRepository(db)
        self._comment_repo = TicketCommentRepository(db)
        self._area_repo = AreaOfConcernRepository(db)
        self._ticket_svc = TicketService(db, auth_client)

    # ── Entry point ───────────────────────────────────────────────────────────

    async def process(self, payload: EmailPayload) -> tuple[int, str] | None:
        now = datetime.now(timezone.utc)

        # 1. Drop OOO / delivery receipts
        if payload.is_auto_reply:
            logger.info("email_ingest: dropping auto-reply message_id=%s", payload.message_id)
            return None

        # 2. Idempotency — skip if already processed
        if await self._thread_repo.get_by_message_id(payload.message_id):
            logger.info("email_ingest: already processed message_id=%s — skipping", payload.message_id)
            return None

        # 3. Route
        try:
            ticket_id = await self._find_existing_ticket(payload)
            if ticket_id:
                await self._add_reply_comment(payload, ticket_id, now)
                return None
            else:
                return await self._create_new_ticket(payload, now)
        except Exception as exc:
            logger.exception("email_ingest: failed message_id=%s: %s", payload.message_id, exc)
            await self._save_failed_thread(payload, now, str(exc))
            raise

    # ── Thread matching ───────────────────────────────────────────────────────

    async def _find_existing_ticket(self, payload: EmailPayload) -> int | None:
        # Priority 1: In-Reply-To header
        if payload.in_reply_to:
            row = await self._thread_repo.get_by_in_reply_to(payload.in_reply_to)
            if row:
                return row.ticket_id

        # Priority 2: References chain (oldest first)
        for ref in payload.references:
            row = await self._thread_repo.get_by_in_reply_to(ref)
            if row:
                return row.ticket_id

        # Priority 3: [TKT-XXXX] in subject
        m = _TICKET_NUM_RE.search(payload.subject)
        if m:
            ticket_number = f"TKT-{m.group(1).zfill(4)}"
            ticket = await self._ticket_repo.get_by_number(ticket_number)
            if ticket:
                return ticket.ticket_id

        return None

    # ── New ticket ────────────────────────────────────────────────────────────

    async def _create_new_ticket(self, payload: EmailPayload, now: datetime) -> tuple[int, str]:
        customer = await self._resolve_customer(payload.sender_email)

        # Resolve area_of_concern by matching subject+body against known areas.
        # This enables score-based assignment for email tickets (same as UI tickets).
        # Returns None if no match — falls through to least-loaded agent globally.
        area_id = await self._resolve_area(payload.subject, payload.body_text or "")

        title = self._clean_subject(payload.subject)

        ticket = await self._ticket_svc.create_ticket(
            payload=TicketCreateRequest(
                title=title,
                description=payload.body_text or payload.subject,
                product="Email",
                environment=Environment.PROD,
                source=TicketSource.EMAIL,
                area_of_concern=area_id,
                attachments=[],
            ),
            current_user_id=customer.id,
        )

        await self._thread_repo.add(EmailThread(
            ticket_id=ticket.ticket_id,
            message_id=payload.message_id,
            in_reply_to=payload.in_reply_to,
            raw_subject=payload.subject,
            sender_email=payload.sender_email,
            direction=EmailDirection.INBOUND,
            raw_body_text=payload.body_text,
            received_at=payload.received_at,
            processed_at=now,
        ))

        # Use a FRESH session for the notification — self._db is still
        # mid-transaction (ticket + thread unflushed). Sharing the session
        # causes asyncpg to time out and corrupts the transaction.
        try:
            async with AsyncSessionFactory() as notif_session:
                await notification_manager.send(
                    request=TicketCreatedRequest(
                        ticket_id=ticket.ticket_id,
                        ticket_number=ticket.ticket_number,
                        ticket_title=ticket.title,
                        customer_id=customer.id,
                    ),
                    db=notif_session,
                    auth_client=self._auth,
                )
                await notif_session.commit()
        except Exception:
            logger.exception(
                "email_ingest: notification failed for ticket_id=%s — ticket still created",
                ticket.ticket_id,
            )

        logger.info(
            "email_ingest: created ticket_id=%s number=%s from=%s area=%s",
            ticket.ticket_id, ticket.ticket_number, payload.sender_email, area_id,
        )
        return ticket.ticket_id, ticket.title

    # ── Reply ─────────────────────────────────────────────────────────────────

    async def _add_reply_comment(
        self, payload: EmailPayload, ticket_id: int, now: datetime
    ) -> None:
        customer = await self._resolve_customer(payload.sender_email)

        # Strip quoted original email — store only what the customer wrote.
        clean_body = self._strip_reply_quotes(payload.body_text or payload.subject)

        await self._comment_repo.add(TicketComment(
            ticket_id=ticket_id,
            author_id=customer.id,
            author_role=UserRole.CUSTOMER.value,
            body=clean_body,
            is_internal=False,
            triggers_hold=False,
            triggers_resume=False,
        ))

        await self._thread_repo.add(EmailThread(
            ticket_id=ticket_id,
            message_id=payload.message_id,
            in_reply_to=payload.in_reply_to,
            raw_subject=payload.subject,
            sender_email=payload.sender_email,
            direction=EmailDirection.INBOUND,
            raw_body_text=payload.body_text,
            received_at=payload.received_at,
            processed_at=now,
        ))

        logger.info(
            "email_ingest: added comment to ticket_id=%s from=%s",
            ticket_id, payload.sender_email,
        )

    # ── Customer resolution ───────────────────────────────────────────────────

    async def _resolve_customer(self, sender_email: str) -> UserDTO:
        """
        Look up the sender in Auth Service by email.
        Auto-provisions a provisional account if not found.
        Raises on network failure — caller handles retry.
        """
        settings = get_settings()
        base = settings.auth_service_url.rstrip("/")

        # Lookup
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(
                    f"{base}/api/v1/auth/users/by-email",
                    params={"email": sender_email},
                )
            if resp.status_code == 200:
                return UserDTO.model_validate(resp.json())
        except httpx.TransportError as exc:
            logger.warning("email_ingest: auth lookup failed for %s: %s", sender_email, exc)

        # Auto-provision
        logger.info("email_ingest: provisioning new customer email=%s", sender_email)
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.post(
                f"{base}/api/v1/auth/provision-external",
                json={
                    "email": sender_email,
                    "role": UserRole.CUSTOMER.value,
                    "full_name": sender_email.split("@")[0],
                },
            )
        resp.raise_for_status()
        return UserDTO.model_validate(resp.json())

    # ── Area resolution ───────────────────────────────────────────────────────

    async def _resolve_area(self, subject: str, body: str) -> int | None:
        """
        Try to match subject + body against known area names from DB.
        Returns area_id of the first case-insensitive substring match, or None.
        """
        try:
            areas = await self._area_repo.get_all()
            if not areas:
                return None

            text = (subject + " " + body).lower()
            for area in areas:
                if area.name.lower() in text:
                    logger.debug(
                        "email_ingest: area matched name=%r area_id=%s",
                        area.name, area.area_id,
                    )
                    return area.area_id
        except Exception:
            logger.exception("email_ingest: area resolution failed — using None")

        return None

    # ── Error capture ─────────────────────────────────────────────────────────

    async def _save_failed_thread(
        self, payload: EmailPayload, now: datetime, error: str
    ) -> None:
        """
        Write a minimal row so failed ingestions are visible in the DB.
        ticket_id is NULL — no ticket was created.
        Rollback first in case the previous exception aborted the transaction.
        """
        try:
            await self._db.rollback()
            self._db.add(EmailThread(
                ticket_id=None,
                message_id=payload.message_id,
                in_reply_to=payload.in_reply_to,
                raw_subject=payload.subject,
                sender_email=payload.sender_email,
                direction=EmailDirection.INBOUND,
                raw_body_text=payload.body_text,
                received_at=payload.received_at,
                processing_error=error[:500],
            ))
            await self._db.flush()
        except Exception:
            logger.exception("email_ingest: could not write failed thread row")

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _strip_reply_quotes(body: str) -> str:
        """
        Remove the quoted original email from a reply body.
        Keeps only the new content the customer actually wrote.

        Handles the most common separators:
          - Outlook:  '________________________________'
          - Outlook:  '-----Original Message-----'
          - Gmail:    'On <date> ... wrote:'
          - Standard: lines starting with '>'
        """
        if not body:
            return body

        lines = body.splitlines()
        cut_at = len(lines)

        for i, line in enumerate(lines):
            s = line.strip()

            if s.startswith("________________________________"):
                cut_at = i
                break

            if s.lower().startswith("-----original message-----"):
                cut_at = i
                break

            if s.startswith("On ") and (
                "wrote:" in s or
                (i + 1 < len(lines) and "wrote:" in lines[i + 1])
            ):
                cut_at = i
                break

            if s.startswith(">"):
                cut_at = i
                break

        result = "\n".join(lines[:cut_at]).strip()
        return result or body

    @staticmethod
    def _clean_subject(subject: str) -> str:
        """
        Strip reply/forward prefixes (including localised variants) and
        [TKT-XXXX] tags from the subject so the ticket title is clean.
        """
        s = subject.strip()
        prefixes = (
            "Re:", "RE:", "re:",
            "Fwd:", "FWD:", "Fw:", "FW:",
            "AW:",          # German
            "RÉP:", "Rép:", # French
            "RIF:",         # Italian
            "回复:",         # Chinese Simplified
        )
        changed = True
        while changed:
            changed = False
            for prefix in prefixes:
                if s.lower().startswith(prefix.lower()):
                    s = s[len(prefix):].strip()
                    changed = True
        return _TICKET_NUM_RE.sub("", s).strip() or subject