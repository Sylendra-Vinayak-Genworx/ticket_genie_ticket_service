from __future__ import annotations

import asyncio
import logging
import re
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from functools import partial

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.constants.enum import EventType, NotificationChannel, NotificationStatus
from src.core.services.email_config_service import EmailConfigService
from src.schemas.notification_schema import (
    AgentCommentRequest,
    AutoClosedRequest,
    CustomerCommentRequest,
    SLABreachedRequest,
    StatusChangedRequest,
    TicketAssignedRequest,
    TicketCreatedRequest,
)
from src.data.models.postgres.notification_log import NotificationLog
from src.data.repositories.notification_log_repository import NotificationLogRepository
from src.data.models.postgres.email_thread import EmailThread, EmailDirection
from src.data.repositories.email_thread_repository import EmailThreadRepository

logger = logging.getLogger(__name__)



def _get_ai_draft():
    from src.core.services.auto_reply_service import get_ai_draft_service
    return get_ai_draft_service()


def _reply_mode():
    from src.core.services.auto_reply_service import ReplyMode
    return ReplyMode


def _ticket_context(**kwargs):
    from src.core.services.auto_reply_service import TicketContext
    return TicketContext(**kwargs)


# ── HTML / text templates for ingest-pipeline outbound emails ─────────────────

_ACK_HTML = """\
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
    .badge {{ display: inline-block; background: #f0f0ff; color: #1a1a2e;
              font-family: monospace; font-weight: 700; font-size: 16px;
              padding: 5px 14px; border-radius: 3px;
              border: 1px solid #c8c8e8; letter-spacing: 1px; }}
    .ftr  {{ padding: 16px 36px; background: #fafaf8;
             color: #999; font-size: 12px; border-top: 1px solid #eee; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hdr"><h1>Support request received</h1></div>
    <div class="body">
      <p>Hi {customer_name},</p>
      <p>
        Thanks for reaching out. We've logged your request and a member of
        our team will follow up shortly.
      </p>
      <p>Your ticket number is <span class="badge">{ticket_number}</span></p>
      <p>
        Simply reply to this email if you have anything to add and we'll
        attach it to your ticket automatically.
      </p>
      <p>— {from_name}</p>
    </div>
    <div class="ftr">
      This is an automated message. Reply only to update ticket {ticket_number}.
    </div>
  </div>
</body>
</html>
"""

_ACK_TEXT = (
    "Hi {customer_name},\n\n"
    "Thanks for reaching out. We've logged your request under ticket "
    "{ticket_number}. A member of our team will follow up shortly.\n\n"
    "Simply reply to this email to add more information to your ticket.\n\n"
    "— {from_name}\n"
)

_CONTINUE_HTML = """\
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
    .badge {{ display: inline-block; background: #f0f0ff; color: #1a1a2e;
              font-family: monospace; font-weight: 700; font-size: 16px;
              padding: 5px 14px; border-radius: 3px;
              border: 1px solid #c8c8e8; letter-spacing: 1px; }}
    .btn  {{ display: inline-block; background: #1a1a2e; color: #fff !important;
             text-decoration: none; padding: 13px 30px; border-radius: 4px;
             font-size: 14px; font-weight: 700; letter-spacing: .5px; margin: 8px 0 4px; }}
    .ftr  {{ padding: 16px 36px; background: #fafaf8;
             color: #999; font-size: 12px; border-top: 1px solid #eee; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hdr"><h1>We've got your reply — {ticket_number}</h1></div>
    <div class="body">
      <p>Hi {customer_name},</p>
      <p>
        We've added your message to ticket
        <span class="badge">{ticket_number}</span>.
      </p>
      <p>
        For the best experience — including real-time updates, file attachments,
        and full conversation history — you can continue the conversation
        directly in our support portal:
      </p>
      <p><a class="btn" href="{ticket_url}">View ticket in portal →</a></p>
      
      </p>
      <p>— {from_name}</p>
    </div>
    <div class="ftr">
      Ticket {ticket_number} · <a href="{ticket_url}">{ticket_url}</a>
    </div>
  </div>
</body>
</html>
"""

_CONTINUE_TEXT = (
    "Hi {customer_name},\n\n"
    "We've added your message to ticket {ticket_number}.\n\n"
    "You can view and continue the conversation in our support portal:\n"
    "{ticket_url}\n\n"
    "— {from_name}\n"
)


class EmailNotificationService:

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = NotificationLogRepository(db)
        self._thread_repo = EmailThreadRepository(db)
        self._config: dict | None = None

    async def _ensure_config(self) -> dict:
        """
        Load and cache SMTP configuration for the lifetime of this service instance.

        Resolution order:
          1. In-memory cache (_config) — avoids repeated DB queries within one
             request/task lifecycle.
          2. Database (EmailConfigService) — used when an active config row exists
             with the required smtp_host and smtp_user fields populated.
          3. Environment variables — final fallback so the service degrades
             gracefully when no DB config is present (e.g. first-run / dev).
        """
        if self._config is not None:
            return self._config

        # ── 1. Try database ────────────────────────────────────────────────
        try:
            service = EmailConfigService(self._db)
            db_config = await service.get_decrypted_config()
            if (
                db_config
                and db_config.get("is_active")
                and db_config.get("smtp_host")
                and db_config.get("smtp_user")
            ):
                logger.info("email_service: using database SMTP configuration")
                self._config = db_config
                return self._config
        except Exception as exc:
            logger.warning("email_service: failed to load database config: %s", exc)

        # ── 2. Fall back to environment ────────────────────────────────────
        logger.info("email_service: using environment SMTP configuration")
        s = get_settings()
        self._config = {
            "smtp_host":      s.SMTP_HOST,
            "smtp_port":      s.SMTP_PORT,
            "smtp_user":      s.SMTP_USER,
            "smtp_password":  s.SMTP_PASSWORD,
            "smtp_from_name": getattr(s, "SMTP_FROM_NAME", "Support Team"),
        }
        return self._config

    # ── Existing lifecycle notifications ──────────────────────────────────────

    async def send_ticket_created(
        self, req: TicketCreatedRequest, recipient_email: str
    ) -> None:
        config = await self._ensure_config()
        subject = f"[{req.ticket_number}] Your support ticket has been received"
        body = (
            f"Hi,\n\n"
            f"We've received your ticket [{req.ticket_number}]: {req.ticket_title}.\n"
            f"Our team will get back to you shortly.\n\n"
            f"— {config['smtp_from_name']}"
        )
        await self._deliver(
            config=config,
            ticket_id=req.ticket_id,
            recipient_id=req.customer_id,
            recipient_email=recipient_email,
            subject=subject,
            body=body,
            event_type=EventType.CREATED.value,
        )

    async def send_status_changed(
        self, req: StatusChangedRequest, recipient_email: str, customer_name: str
    ) -> None:
        config = await self._ensure_config()
        draft = await _get_ai_draft().draft(
            mode=_reply_mode().NOTIFY_CUSTOMER,
            context=_ticket_context(
                ticket_number=req.ticket_number,
                ticket_title=req.ticket_title,
                status=req.new_status,
                severity=req.severity,
                customer_name=customer_name,
                agent_name=req.agent_name,
            ),
            event=f"Your ticket status changed from {req.old_status} to {req.new_status}.",
        )
        await self._deliver(
            config=config,
            ticket_id=req.ticket_id,
            recipient_id=req.customer_id,
            recipient_email=recipient_email,
            subject=draft.subject,
            body=draft.body,
            event_type=EventType.STATUS_CHANGED.value,
        )

    async def send_agent_comment(
        self, req: AgentCommentRequest, recipient_email: str, customer_name: str
    ) -> None:
        config = await self._ensure_config()
        draft = await _get_ai_draft().draft(
            mode=_reply_mode().NOTIFY_CUSTOMER,
            context=_ticket_context(
                ticket_number=req.ticket_number,
                ticket_title=req.ticket_title,
                status=req.status,
                severity=req.severity,
                customer_name=customer_name,
                agent_name=req.agent_name,
                history=req.history,
            ),
            event=req.comment_body,
        )
        await self._deliver(
            config=config,
            ticket_id=req.ticket_id,
            recipient_id=req.customer_id,
            recipient_email=recipient_email,
            subject=draft.subject,
            body=draft.body,
            event_type="AGENT_COMMENT",
        )

    async def send_customer_comment(
        self, req: CustomerCommentRequest, recipient_email: str
    ) -> None:
        config = await self._ensure_config()
        subject = f"[{req.ticket_number}] New reply from {req.customer_name}"
        body = (
            f"Hi,\n\n"
            f"{req.customer_name} replied on [{req.ticket_number}]: {req.ticket_title}.\n\n"
            f'"{req.comment_body}"\n\n'
            f"Log in to the portal to respond.\n\n"
            f"— {config['smtp_from_name']}"
        )
        await self._deliver(
            config=config,
            ticket_id=req.ticket_id,
            recipient_id=req.assignee_id,
            recipient_email=recipient_email,
            subject=subject,
            body=body,
            event_type="CUSTOMER_COMMENT",
        )

    async def send_ticket_assigned(
        self, req: TicketAssignedRequest, recipient_email: str, agent_name: str
    ) -> None:
        config = await self._ensure_config()
        draft = await _get_ai_draft().draft(
            mode=_reply_mode().NOTIFY_AGENT,
            context=_ticket_context(
                ticket_number=req.ticket_number,
                ticket_title=req.ticket_title,
                status=req.status,
                severity=req.severity,
                customer_name=req.customer_name,
                agent_name=agent_name,
            ),
            event=f"Ticket [{req.ticket_number}] has been assigned to you. Please review and begin work.",
        )
        await self._deliver(
            config=config,
            ticket_id=req.ticket_id,
            recipient_id=req.assignee_id,
            recipient_email=recipient_email,
            subject=draft.subject,
            body=draft.body,
            event_type=EventType.ASSIGNED.value,
        )

    async def send_sla_breached(
        self, req: SLABreachedRequest, recipient_email: str, lead_name: str
    ) -> None:
        config = await self._ensure_config()
        draft = await _get_ai_draft().draft(
            mode=_reply_mode().NOTIFY_AGENT,
            context=_ticket_context(
                ticket_number=req.ticket_number,
                ticket_title=req.ticket_title,
                status=req.status,
                severity=req.severity,
                customer_name=req.customer_name,
                agent_name=lead_name,
            ),
            event=(
                f"[{req.ticket_number}] has breached its {req.breach_type} SLA. "
                f"Immediate escalation action is required."
            ),
        )
        await self._deliver(
            config=config,
            ticket_id=req.ticket_id,
            recipient_id=req.lead_id,
            recipient_email=recipient_email,
            subject=draft.subject,
            body=draft.body,
            event_type=EventType.SLA_BREACHED.value,
        )

    async def send_auto_closed(
        self, req: AutoClosedRequest, recipient_email: str, customer_name: str
    ) -> None:
        config = await self._ensure_config()
        subject = f"[{req.ticket_number}] Your ticket has been closed"
        body = (
            f"Hi {customer_name},\n\n"
            f"Your ticket [{req.ticket_number}]: {req.ticket_title} has been "
            f"automatically closed after being resolved with no further activity.\n\n"
            f"If you still need help, please open a new ticket.\n\n"
            f"— {config['smtp_from_name']}"
        )
        await self._deliver(
            config=config,
            ticket_id=req.ticket_id,
            recipient_id=req.customer_id,
            recipient_email=recipient_email,
            subject=subject,
            body=body,
            event_type="AUTO_CLOSED",
        )

    # ── Email ingest pipeline outbound emails ─────────────────────────────────

    async def send_ticket_ack(
        self,
        *,
        ticket_id: int,
        recipient_id: str,
        recipient_email: str,
        customer_name: str,
        ticket_number: str,
        original_message_id: str,
    ) -> None:
        config = await self._ensure_config()
        from_name = config.get("smtp_from_name", "Support Team")

        html_body = _ACK_HTML.format(
            customer_name=customer_name,
            ticket_number=ticket_number,
            from_name=from_name,
        )
        text_body = _ACK_TEXT.format(
            customer_name=customer_name,
            ticket_number=ticket_number,
            from_name=from_name,
        )

        await self._deliver(
            config=config,
            ticket_id=ticket_id,
            recipient_id=recipient_id,
            recipient_email=recipient_email,
            subject=f"[{ticket_number}] Support request received",
            body=text_body,
            html_body=html_body,
            event_type="EMAIL_INGEST_ACK",
            in_reply_to=original_message_id,
            references=original_message_id,
        )
        logger.info(
            "email_service: sent ingest ACK to=%s ticket=%s",
            recipient_email, ticket_number,
        )

    async def send_continue_in_ui(
        self,
        *,
        ticket_id: int,
        recipient_id: str,
        recipient_email: str,
        customer_name: str,
        customer_role: str,
        ticket_number: str,
        original_message_id: str,
    ) -> None:

        from src.utils.portal_token import generate_portal_token

        config = await self._ensure_config()
        from_name = config.get("smtp_from_name", "Support Team")

        s = get_settings()
        base_url = getattr(s, "APP_BASE_URL", "http://localhost").rstrip("/")

        ticket_url = f"{base_url}/login"

        html_body = _CONTINUE_HTML.format(
            customer_name=customer_name,
            ticket_number=ticket_number,
            ticket_url=ticket_url,
            from_name=from_name,
        )
        text_body = _CONTINUE_TEXT.format(
            customer_name=customer_name,
            ticket_number=ticket_number,
            ticket_url=ticket_url,
            from_name=from_name,
        )

        await self._deliver(
            config=config,
            ticket_id=ticket_id,
            recipient_id=recipient_id,
            recipient_email=recipient_email,
            subject=f"[{ticket_number}] Continue your conversation on the support portal by using your credentials",
            body=text_body,
            html_body=html_body,
            event_type="EMAIL_INGEST_CONTINUE_UI",
            in_reply_to=original_message_id,
            references=original_message_id,
        )
        logger.info(
            "email_service: sent continue-in-UI to=%s ticket=%s url=%s",
            recipient_email, ticket_number, ticket_url,
        )

    async def send_clarification_request(
        self,
        *,
        recipient_email: str,
        customer_name: str,
        original_message_id: str,
        original_subject: str,
        missing_fields: list[str],
    ) -> None:

        config = await self._ensure_config()

        missing_bullet_list = "\n".join(f"  • {m}" for m in missing_fields)
        event_text = (
            "We received your support request but need a bit more detail before we "
            "can create a ticket and assign it to an agent.\n\n"
            f"Please send us a new email with the following information:\n{missing_bullet_list}"
        )

        draft = await _get_ai_draft().draft(
            mode=_reply_mode().CLARIFY_CUSTOMER,
            context=_ticket_context(
                ticket_number="",
                ticket_title=original_subject,
                status="",
                severity="MEDIUM",
                customer_name=customer_name,
                agent_name=None,
            ),
            event=event_text,
        )

        # Strip the subject from AI — use a clean Re: of the original instead.
        # The LLM tends to invent unhelpful subjects like "Ticket Number Not Assigned".
        clean_original = re.sub(r"^(re|fwd?):\s*", "", original_subject, flags=re.IGNORECASE).strip()
        subject = f"Re: {clean_original}"

        # No ticket exists yet — call _smtp_send directly so we don't write
        # a NotificationLog row with a NULL/invalid ticket_id FK.
        smtp_cfg = config
        outbound_domain = smtp_cfg.get("smtp_user", "support@ticketgenie.ai").split("@")[-1]
        from email.utils import make_msgid as _make_msgid
        outbound_mid = _make_msgid(domain=outbound_domain)
        if smtp_cfg.get("smtp_user"):
            import asyncio as _asyncio
            from functools import partial as _partial
            loop = _asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                _partial(
                    self._smtp_send,
                    config=smtp_cfg,
                    to=recipient_email,
                    subject=subject,
                    body=draft.body,
                    message_id=outbound_mid,
                    in_reply_to=original_message_id,
                    references=original_message_id,
                ),
            )
        else:
            logger.info(
                "email_service [DEV]: clarify to=%s subject=%r\n%s",
                recipient_email, subject, draft.body,
            )
        logger.info(
            "email_service: sent clarification request to=%s subject=%r missing=%s",
            recipient_email, original_subject, missing_fields,
        )

    async def _deliver(
        self,
        config: dict,
        ticket_id: int,
        recipient_id: str,
        recipient_email: str,
        subject: str,
        body: str,
        event_type: str,
        html_body: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
    ) -> None:
   
        now = datetime.now(timezone.utc)
        status = NotificationStatus.PENDING

     
        smtp_domain = config.get("smtp_user", "support@ticketgenie.ai").split("@")[-1]
        outbound_message_id = make_msgid(domain=smtp_domain)

        try:
            if config.get("smtp_user"):
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    partial(
                        self._smtp_send,
                        config=config,
                        to=recipient_email,
                        subject=subject,
                        body=body,
                        html_body=html_body,
                        in_reply_to=in_reply_to,
                        references=references,
                        message_id=outbound_message_id,
                    ),
                )
            else:
                logger.info(
                    "email_service [DEV]: to=%s subject=%r\n%s",
                    recipient_email, subject, body,
                )
            status = NotificationStatus.SENT
        except Exception as exc:
            logger.exception(
                "email_service: failed event=%s to=%s: %s",
                event_type, recipient_email, exc,
            )
            status = NotificationStatus.FAILED

        await self._repo.add(NotificationLog(
            ticket_id=ticket_id,
            recipient_user_id=recipient_id,
            channel=NotificationChannel.EMAIL,
            event_type=event_type,
            status=status,
            sent_at=now if status == NotificationStatus.SENT else None,
        ))

        # Record the outbound email in email_threads so that when the customer
        # replies, _find_existing_ticket can match their In-Reply-To header to
        # this message_id and route the reply to the correct ticket.
        if status == NotificationStatus.SENT:
            try:
                await self._thread_repo.add(EmailThread(
                    ticket_id=ticket_id,
                    message_id=outbound_message_id,
                    in_reply_to=in_reply_to,
                    raw_subject=subject,
                    sender_email=config.get("smtp_user", ""),
                    direction=EmailDirection.OUTBOUND,
                    raw_body_text=body,
                    received_at=now,
                    processed_at=now,
                ))
            except Exception:
                logger.exception(
                    "email_service: failed to record outbound thread row "
                    "ticket_id=%s — email was still sent", ticket_id
                )

    def _smtp_send(
        self,
        *,
        config: dict,
        to: str,
        subject: str,
        body: str,
        html_body: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
        message_id: str | None = None,
    ) -> None:
        """
        Sync SMTP send — called via run_in_executor so it never blocks the loop.

        Builds a multipart/alternative message always (plain-text + optional HTML).
        Threading headers (Message-ID, In-Reply-To, References) are set when provided.

        Port 465 → implicit SSL (SMTP_SSL).
        Port 587 or any other → STARTTLS (SMTP + starttls).
        """
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain", "utf-8"))
        if html_body:
            msg.attach(MIMEText(html_body, "html", "utf-8"))

        msg["Subject"] = subject
        msg["From"]    = f"{config.get('smtp_from_name', 'Support Team')} <{config['smtp_user']}>"
        msg["To"]      = to

        if message_id:
            msg["Message-ID"] = message_id
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references

        smtp_host = config["smtp_host"]
        smtp_port = int(config.get("smtp_port", 587))
        smtp_user = config["smtp_user"]
        smtp_pass = config["smtp_password"]

        if smtp_port == 465:
            # Implicit SSL — no STARTTLS handshake needed
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as smtp:
                smtp.login(smtp_user, smtp_pass)
                smtp.sendmail(smtp_user, to, msg.as_string())
        else:
            # Explicit TLS via STARTTLS (port 587 or custom)
            with smtplib.SMTP(smtp_host, smtp_port) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(smtp_user, smtp_pass)
                smtp.sendmail(smtp_user, to, msg.as_string())

        logger.info("email_service: sent event to=%s subject=%r", to, subject)