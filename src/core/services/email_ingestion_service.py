

from __future__ import annotations

import logging
import re
import secrets
import string
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.constants.enum import Environment, NotificationChannel, TicketSource, UserRole
from src.core.services.classification_service import ClassificationService
from src.core.services.notification.email_service import EmailNotificationService
from src.core.services.notification.manager import notification_manager
from src.core.services.ticket_service import TicketService
from src.data.clients.auth_client import AuthServiceClient, UserDTO
from src.data.clients.postgres_client import AsyncSessionFactory
from src.data.models.postgres.email_thread import EmailDirection, EmailThread
from src.data.models.postgres.ticket_comment import TicketComment
from src.data.repositories.area_of_concern_repository import AreaOfConcernRepository
from src.data.repositories.email_thread_repository import EmailThreadRepository
from src.data.repositories.keyword_repository import KeywordRepository
from src.data.repositories.ticket_comment_repository import TicketCommentRepository
from src.data.repositories.ticket_repository import TicketRepository
from src.schemas.email_schema import EmailPayload, EmailTicketParseResult, _groq_async
from src.schemas.notification_schema import TicketCreatedRequest
from src.schemas.ticket_schema import TicketCreateRequest

logger = logging.getLogger(__name__)

_TICKET_NUM_RE = re.compile(r"\[TKT-(\d+)\]", re.IGNORECASE)


def _generate_temp_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))



_WELCOME_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <style>
    body  {{ font-family: Georgia, serif; background: #f5f5f0; margin: 0; padding: 0; }}
    .wrap {{ max-width: 560px; margin: 40px auto; background: #fff;
             border-radius: 4px; overflow: hidden; border: 1px solid #e5e5e0; }}
    .hdr  {{ background: #1a1a2e; padding: 28px 36px; }}
    .hdr h1 {{ color: #fff; margin: 0; font-size: 18px;
               font-weight: 400; letter-spacing: .5px; }}
    .body {{ padding: 32px 36px; color: #333; line-height: 1.7; font-size: 15px; }}
    .body p {{ margin: 0 0 16px; }}
    .cred {{ background: #f0f4ff; border: 1px solid #c8d4f0; border-radius: 4px;
             padding: 16px 20px; font-family: monospace; font-size: 14px;
             margin: 16px 0; line-height: 2; }}
    .btn  {{ display: inline-block; background: #2563eb; color: #fff !important;
             padding: 12px 28px; border-radius: 6px; text-decoration: none;
             font-weight: 600; font-size: 14px; margin: 8px 0; }}
    .ftr  {{ padding: 16px 36px; background: #fafaf8;
             color: #999; font-size: 12px; border-top: 1px solid #eee; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hdr"><h1>Welcome to {from_name}</h1></div>
    <div class="body">
      <p>Hi {customer_name},</p>
      <p>
        We received your support request and automatically created a portal
        account so you can track your ticket and get faster help in the future.
      </p>
      <p>Your login credentials:</p>
      <div class="cred">
        <strong>Email:</strong> {email}<br/>
        <strong>Temporary Password:</strong> {temp_password}
      </div>
      <p>
        <a href="{login_url}" class="btn">Sign in to the portal →</a>
      </p>
      <p>
      
        Your support ticket <strong>{ticket_number}</strong> is already waiting for you there.
      </p>
      <p>— {from_name}</p>
    </div>
    <div class="ftr">
      If you did not send a support email to us, please ignore this message.
    </div>
  </div>
</body>
</html>
"""

_WELCOME_TEXT = (
    "Hi {customer_name},\n\n"
    "We received your support request and created a portal account for you.\n\n"
    "Login credentials:\n"
    "  Email:              {email}\n"
    "  Temporary Password: {temp_password}\n\n"
    "Sign in at: {login_url}\n\n"
    
    "Your ticket {ticket_number} is already waiting for you in the portal.\n\n"
    "— {from_name}\n"
)


class EmailIngestService:

    def __init__(self, db: AsyncSession, auth_client: AuthServiceClient) -> None:
        self._db = db
        self._auth = auth_client
        self._thread_repo = EmailThreadRepository(db)
        self._ticket_repo = TicketRepository(db)
        self._comment_repo = TicketCommentRepository(db)
        self._area_repo = AreaOfConcernRepository(db)
        self._ticket_svc = TicketService(db, auth_client)
        self._classifier = ClassificationService(KeywordRepository(db))

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
        def _norm(mid: str) -> str:
            """Lowercase + ensure angle-bracket wrapping — mirrors EmailPayload.normalise_message_id
            and how _deliver stores outbound message_ids."""
            mid = mid.strip().lower()
            if not mid.startswith("<"):
                mid = f"<{mid}"
            if not mid.endswith(">"):
                mid = f"{mid}>"
            return mid

        # Priority 1: In-Reply-To header
        if payload.in_reply_to:
            row = await self._thread_repo.get_by_in_reply_to(_norm(payload.in_reply_to))
            if row:
                return row.ticket_id

        # Priority 2: References chain (oldest first)
        for ref in payload.references:
            row = await self._thread_repo.get_by_in_reply_to(_norm(ref))
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

    async def _create_new_ticket(
        self, payload: EmailPayload, now: datetime
    ) -> tuple[int, str]:
        # 1. Resolve (or create) the customer — captures is_new_user flag
        customer, is_new_user, temp_password = await self._resolve_customer(
            payload.sender_email
        )

        # 2. Load areas from DB — passed to the LLM so it picks a name that
        #    exists in the DB, and the Pydantic model_validator resolves the id.
        areas = await self._area_repo.get_all()

        # 3. Parse the email with Groq — areas list injected so:
        #      • The system prompt lists exact DB area names the LLM must choose from
        #      • The model_validator resolves area_of_concern_id in one step
        parsed: EmailTicketParseResult = await _groq_async(
            subject=payload.subject,
            body=payload.body_text or "",
            areas=areas,
        )

        # 4. Always run ClassificationService against the live keyword_rules table
        #    regardless of whether Groq succeeded or fell back.  This is the
        #    authoritative severity source — it overwrites whatever the LLM or
        #    fallback produced so admin-configured keyword rules are always respected.
        classification = await self._classifier.classify(parsed.title, parsed.description)
        parsed.severity = classification.severity.value
        logger.info(
            "email_ingest: classified message_id=%s title=%r product=%r "
            "severity=%r (rule=%s keyword=%r) area_name=%r area_id=%s",
            payload.message_id, parsed.title, parsed.product,
            parsed.severity, classification.matched_rule_id,
            classification.matched_keyword,
            parsed.area_of_concern_name, parsed.area_of_concern_id,
        )

        # 5. Create ticket — area_of_concern_id resolved by Pydantic, severity by ClassificationService
        ticket = await self._ticket_svc.create_ticket(
            payload=TicketCreateRequest(
                title=parsed.title,
                description=parsed.description,
                product=parsed.product,
                environment=Environment.PROD,
                source=TicketSource.EMAIL,
                area_of_concern=parsed.area_of_concern_id,
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

        customer_name = (
            getattr(customer, "full_name", None)
            or payload.sender_email.split("@")[0]
        )

        # 5a. If this is a brand-new user, send credentials email instead of
        #     (or in addition to) the normal ACK so they know how to log in.
        if is_new_user and temp_password:
            await self._send_credentials_email(
                sender_email=payload.sender_email,
                customer_name=customer_name,
                temp_password=temp_password,
                ticket_number=ticket.ticket_number,
                original_message_id=payload.message_id,
                ticket_id=ticket.ticket_id,
                recipient_id=customer.id,
            )

        # 6. In-app notification
        try:
            # Skip email channel if this ticket came from email, as an ACK has already been sent
            skip_channels = []
            if ticket.source == TicketSource.EMAIL:
                skip_channels = [NotificationChannel.EMAIL]

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
                    skip_channels=skip_channels,
                )
                await notif_session.commit()
        except Exception:
            logger.exception(
                "email_ingest: notification failed for ticket_id=%s — ticket still created",
                ticket.ticket_id,
            )

        logger.info(
            "email_ingest: created ticket_id=%s number=%s from=%s area=%s new_user=%s",
            ticket.ticket_id, ticket.ticket_number,
            payload.sender_email,is_new_user,
        )
        return ticket.ticket_id, ticket.title


    async def _add_reply_comment(
        self, payload: EmailPayload, ticket_id: int, now: datetime
    ) -> None:
        customer, _, _ = await self._resolve_customer(payload.sender_email)

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
                        customer_role=customer.role,
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

    async def _resolve_customer(
        self, sender_email: str
    ) -> tuple[UserDTO, bool, str | None]:
        """
        Look up the sender in Auth Service by email.

        Returns (user_dto, is_new_user, temp_password).

        NEW USER PATH
        ─────────────
        If the email is not registered, create a full customer account via
        the Auth Service admin/users endpoint (same endpoint as admin-created
        staff accounts).  A temporary password is generated, stored in the
        return value so the caller can include it in the credentials email,
        and the account is created with role='user'.

        EXISTING USER PATH
        ──────────────────
        Returns (user_dto, False, None).

        Raises on network failure — the Celery task handles retry.
        """
        settings = get_settings()
        base = settings.auth_service_url.rstrip("/")

        # 1. Try to find existing user
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(
                    f"{base}/api/v1/auth/users/by-email",
                    params={"email": sender_email},
                )
            if resp.status_code == 200:
                logger.debug("email_ingest: found existing user email=%s", sender_email)
                return UserDTO.model_validate(resp.json()), False, None
        except httpx.TransportError as exc:
            logger.warning(
                "email_ingest: auth lookup failed for %s: %s", sender_email, exc
            )

        # 2. User not found — create a full account with credentials
        logger.info(
            "email_ingest: sender not registered, creating account email=%s", sender_email
        )
        temp_password = _generate_temp_password()
        display_name  = sender_email.split("@")[0].replace(".", " ").title()

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                create_resp = await client.post(
                    f"{base}/api/v1/auth/signup",
                    json={
                        "email":      sender_email,
                        "password":   temp_password,
                        "full_name":  display_name,
                        "role":       "user",
                    },
                )
            create_resp.raise_for_status()
            data = create_resp.json()
            # signup returns { user: {...}, message: "..." }
            user_data = data.get("user") or data
            user_dto  = UserDTO.model_validate(user_data)
            logger.info(
                "email_ingest: created new customer account user_id=%s email=%s",
                user_dto.id, sender_email,
            )
            return user_dto, True, temp_password

        except httpx.HTTPStatusError as exc:
            # 409 = email already registered (race condition) — fetch and return
            if exc.response.status_code == 409:
                logger.info(
                    "email_ingest: race — account already exists for %s", sender_email
                )
                async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                    resp = await client.get(
                        f"{base}/api/v1/auth/users/by-email",
                        params={"email": sender_email},
                    )
                resp.raise_for_status()
                return UserDTO.model_validate(resp.json()), False, None
            raise

    # ── Credentials email ─────────────────────────────────────────────────────

    async def _send_credentials_email(
        self,
        *,
        sender_email: str,
        customer_name: str,
        temp_password: str,
        ticket_number: str,
        original_message_id: str,
        ticket_id: int,
        recipient_id: str,
    ) -> None:
        """
        Send a welcome-with-credentials email to a newly registered customer.
        Goes through EmailNotificationService._deliver() so it follows the
        same SMTP config / logging / dev-mode path as all other outbound mail.
        Fire-and-forget — a send failure never rolls back the ticket.
        """
        settings = get_settings()
        login_url = f"{settings.FRONTEND_URL.rstrip('/')}/login"

        try:
            async with AsyncSessionFactory() as cred_session:
                svc = EmailNotificationService(cred_session)
                config = await svc._ensure_config()
                from_name = config["smtp_from_name"]

                subject = f"[{ticket_number}] Your TicketGenie account credentials"
                html = _WELCOME_HTML.format(
                    customer_name=customer_name,
                    email=sender_email,
                    temp_password=temp_password,
                    login_url=login_url,
                    ticket_number=ticket_number,
                    from_name=from_name,
                )
                text = _WELCOME_TEXT.format(
                    customer_name=customer_name,
                    email=sender_email,
                    temp_password=temp_password,
                    login_url=login_url,
                    ticket_number=ticket_number,
                    from_name=from_name,
                )
                await svc._deliver(
                    config=config,
                    ticket_id=ticket_id,
                    recipient_id=recipient_id,
                    recipient_email=sender_email,
                    subject=subject,
                    body=text,
                    event_type="EMAIL_INGEST_CREDENTIALS",
                    html_body=html,
                    in_reply_to=original_message_id,
                    references=original_message_id,
                )
                await cred_session.commit()
            logger.info(
                "email_ingest: sent credentials email to=%s ticket=%s",
                sender_email, ticket_number,
            )
        except Exception:
            logger.exception(
                "email_ingest: credentials email failed for %s — ticket still created",
                sender_email,
            )

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