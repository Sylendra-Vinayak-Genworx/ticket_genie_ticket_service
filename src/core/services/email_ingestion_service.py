"""
core/services/email_ingest_service.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Routes a parsed inbound EmailPayload to one of two paths:

NEW TICKET
──────────
  No matching ticket found → call TicketService.create_ticket()
  (runs the full pipeline: classify → SLA → ACKNOWLEDGED → auto-assign)
  and save an EmailThread row linking this email to the new ticket.

  Outbound: send ACK email via EmailNotificationService.send_ticket_ack()
  so the customer knows their request was received.  The ACK sets
  In-Reply-To / References pointing at the customer's original message
  so the reply lands in the same mail thread.

REPLY (add comment)
───────────────────
  Matching ticket found → add a TicketComment with the email body
  and save a new EmailThread row linked to the same ticket.

  Outbound (first reply only): after the customer's first reply comment,
  send a "continue in UI" email via
  EmailNotificationService.send_continue_in_ui() with a direct link to
  the ticket portal so they can switch to the richer web interface.
  Subsequent replies are ingested silently — the portal link is sent once.

  "First reply" is detected by counting existing EmailThread rows for
  the ticket *before* writing the new one — a count of exactly 1 means
  only the original inbound email exists, making this the first reply.

Both outbound sends go through EmailNotificationService so they:
  • Use the same SMTP config source (DB → env fallback) as all other
    notification emails — no second SMTP stack.
  • Are logged to the notification_log table for observability.
  • Share the same delivery / retry / dev-mode logic.

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

Error handling
──────────────
  Any exception is caught, logged, and a failed EmailThread row is written
  with ticket_id=NULL so failures are visible in the DB and can be retried.
  The exception is then re-raised so the Celery task can decide on retry.

  Outbound email failures are caught and logged but never allowed to fail
  the ingest itself — the ticket/comment is always committed first.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.constants.enum import Environment, TicketSource, UserRole
from src.core.services.notification.email_service import EmailNotificationService
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
        area_id  = await self._resolve_area(payload.subject, payload.body_text or "")
        title    = self._clean_subject(payload.subject)

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

        # ── ACK email ─────────────────────────────────────────────────────────
        # Goes through EmailNotificationService so the SMTP config source (DB →
        # env), notification_log entry, and dev-mode short-circuit are consistent
        # with every other outbound email in the system.
        #
        # Fresh session required: self._db is still mid-transaction (ticket +
        # thread not yet flushed). Reusing it stalls asyncpg and corrupts the
        # transaction — same isolation pattern as the notification block below.
        #
        # Fire-and-forget: a send failure must never roll back the ticket.
        try:
            customer_name = (
                getattr(customer, "full_name", None)
                or payload.sender_email.split("@")[0]
            )
            async with AsyncSessionFactory() as ack_session:
                await EmailNotificationService(ack_session).send_ticket_ack(
                    ticket_id=ticket.ticket_id,
                    recipient_id=customer.id,
                    recipient_email=payload.sender_email,
                    customer_name=customer_name,
                    ticket_number=ticket.ticket_number,
                    original_message_id=payload.message_id,
                )
                await ack_session.commit()
        except Exception:
            logger.exception(
                "email_ingest: ACK email failed for ticket_id=%s — ticket still created",
                ticket.ticket_id,
            )

        # ── In-app notification ───────────────────────────────────────────────
        # Fresh session for the same reason as the ACK block above.
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

        # Count existing thread rows BEFORE writing the new one.
        # count == 1  →  only the original inbound email exists
        #             →  this is the customer's first reply → send portal link
        # count  > 1  →  subsequent reply → ingest silently
        is_first_reply = await self._thread_repo.count_by_ticket_id(ticket_id) == 1

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
            "email_ingest: added comment to ticket_id=%s from=%s first_reply=%s",
            ticket_id, payload.sender_email, is_first_reply,
        )

        # ── "Continue in UI" reply (first customer reply only) ────────────────
        # Fresh session + fire-and-forget — same reasoning as ACK block above.
        if is_first_reply:
            try:
                ticket = await self._ticket_repo.get_by_id(ticket_id)
                ticket_number = ticket.ticket_number if ticket else f"TKT-{ticket_id}"
                customer_name = (
                    getattr(customer, "full_name", None)
                    or payload.sender_email.split("@")[0]
                )
                async with AsyncSessionFactory() as ui_session:
                    await EmailNotificationService(ui_session).send_continue_in_ui(
                        ticket_id=ticket_id,
                        recipient_id=customer.id,
                        recipient_email=payload.sender_email,
                        customer_name=customer_name,
                        ticket_number=ticket_number,
                        original_message_id=payload.message_id,
                    )
                    await ui_session.commit()
            except Exception:
                logger.exception(
                    "email_ingest: continue-in-UI email failed for ticket_id=%s "
                    "— comment still saved",
                    ticket_id,
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
        if not body:
            return body
        lines = body.splitlines()
        cut_at = len(lines)
        for i, line in enumerate(lines):
            s = line.strip()
            if s.startswith("________________________________"):
                cut_at = i; break
            if s.lower().startswith("-----original message-----"):
                cut_at = i; break
            if s.startswith("On ") and (
                "wrote:" in s or
                (i + 1 < len(lines) and "wrote:" in lines[i + 1])
            ):
                cut_at = i; break
            if s.startswith(">"):
                cut_at = i; break
        result = "\n".join(lines[:cut_at]).strip()
        return result or body

    @staticmethod
    def _clean_subject(subject: str) -> str:
        s = subject.strip()
        prefixes = (
            "Re:", "RE:", "re:",
            "Fwd:", "FWD:", "Fw:", "FW:",
            "AW:", "RÉP:", "Rép:", "RIF:", "回复:",
        )
        changed = True
        while changed:
            changed = False
            for prefix in prefixes:
                if s.lower().startswith(prefix.lower()):
                    s = s[len(prefix):].strip()
                    changed = True
        return _TICKET_NUM_RE.sub("", s).strip() or subject