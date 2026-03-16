"""
core/services/notification/email_service.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Email notification service — reads SMTP config from database,
falls back to env if database config is not available.

Outbound email triggers
───────────────────────
Ticket lifecycle (existing):
  send_ticket_created     — customer: ticket logged
  send_status_changed     — customer: status update (AI-drafted)
  send_agent_comment      — customer: agent replied (AI-drafted)
  send_customer_comment   — agent:    customer replied
  send_ticket_assigned    — agent:    ticket assigned (AI-drafted)
  send_sla_breached       — lead:     SLA breach alert (AI-drafted)
  send_auto_closed        — customer: ticket auto-closed

Email ingest pipeline (new):
  send_ticket_ack         — customer: ACK on new ticket created via email
                            threads correctly via In-Reply-To so the reply
                            lands in the same mail thread
  send_continue_in_ui     — customer: first reply received, include portal
                            link so they can switch to the richer UI

All outbound sends share the same _load_config → _deliver → _smtp_send
pipeline so SMTP config, delivery logging, and error handling are
consistent across every trigger.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import partial

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.constants.enum import EventType, NotificationChannel, NotificationStatus
from src.core.services.auto_reply_service import AIDraftService, ReplyMode, TicketContext
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

logger = logging.getLogger(__name__)

_ai_draft = AIDraftService()


# ── HTML / text templates for ingest-pipeline outbound emails ─────────────────
#
# These are intentionally plain and readable — they come from an automated
# support pipeline, not a marketing campaign.  The From-name and ticket
# number are the only branding needed.

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
      <p>
        You can still reply by email if you prefer; both channels update
        the same ticket.
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
    "You can still reply by email if you prefer — both channels update "
    "the same ticket.\n\n"
    "— {from_name}\n"
)


class EmailNotificationService:

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = NotificationLogRepository(db)
        self._config: dict | None = None

    async def _load_config(self) -> dict:
        """Load SMTP configuration from database or fallback to env."""
        if self._config:
            return self._config

        # Try database first
        try:
            service = EmailConfigService(self._db)
            db_config = await service.get_decrypted_config()
            if db_config and db_config.get("is_active"):
                logger.info("email_service: using database SMTP configuration")
                self._config = db_config
                return self._config
        except Exception as e:
            logger.warning("email_service: failed to load db config: %s", e)

        # Fallback to environment
        logger.info("email_service: using environment SMTP configuration")
        s = get_settings()
        self._config = {
            "smtp_host": s.SMTP_HOST,
            "smtp_port": s.SMTP_PORT,
            "smtp_user": s.SMTP_USER,
            "smtp_password": s.SMTP_PASSWORD,
            "smtp_from_name": getattr(s, "SMTP_FROM_NAME", "Support Team"),
        }
        return self._config

    # ── Existing lifecycle notifications ──────────────────────────────────────

    async def send_ticket_created(
        self, req: TicketCreatedRequest, recipient_email: str
    ) -> None:
        config = await self._load_config()
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
        config = await self._load_config()
        draft = await _ai_draft.draft(
            mode=ReplyMode.NOTIFY_CUSTOMER,
            context=TicketContext(
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
        config = await self._load_config()
        draft = await _ai_draft.draft(
            mode=ReplyMode.NOTIFY_CUSTOMER,
            context=TicketContext(
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
        config = await self._load_config()
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
        config = await self._load_config()
        draft = await _ai_draft.draft(
            mode=ReplyMode.NOTIFY_AGENT,
            context=TicketContext(
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
        config = await self._load_config()
        draft = await _ai_draft.draft(
            mode=ReplyMode.NOTIFY_AGENT,
            context=TicketContext(
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
        config = await self._load_config()
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
        """
        ACK sent immediately after a new ticket is created from an inbound email.

        Sets In-Reply-To / References pointing at the customer's original
        message so this ACK lands in the same mail thread in their client.
        The customer can reply to this email and it will be matched back to
        the ticket via the In-Reply-To chain.
        """
        config = await self._load_config()
        from_name = config["smtp_from_name"]
        subject = f"[{ticket_number}] We received your support request"
        html = _ACK_HTML.format(
            customer_name=customer_name,
            ticket_number=ticket_number,
            from_name=from_name,
        )
        text = _ACK_TEXT.format(
            customer_name=customer_name,
            ticket_number=ticket_number,
            from_name=from_name,
        )
        await self._deliver(
            config=config,
            ticket_id=ticket_id,
            recipient_id=recipient_id,
            recipient_email=recipient_email,
            subject=subject,
            body=text,
            event_type="EMAIL_INGEST_ACK",
            html_body=html,
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
        ticket_number: str,
        original_message_id: str,
    ) -> None:
        """
        Sent after the customer's first email reply on a ticket.

        Includes a direct link to the ticket in the web portal so they can
        switch to the richer UI for subsequent messages. Sent only once —
        the ingest service detects first-reply by counting existing thread
        rows before writing the new one.
        """
        config = await self._load_config()
        from_name = config["smtp_from_name"]

        s = get_settings()
        base_url = getattr(s, "APP_BASE_URL", "http://localhost").rstrip("/")
        ticket_url = f"{base_url}/tickets/{ticket_id}"

        subject = f"[{ticket_number}] Your reply was received — continue in the portal"
        html = _CONTINUE_HTML.format(
            customer_name=customer_name,
            ticket_number=ticket_number,
            ticket_url=ticket_url,
            from_name=from_name,
        )
        text = _CONTINUE_TEXT.format(
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
            subject=subject,
            body=text,
            event_type="EMAIL_INGEST_CONTINUE_UI",
            html_body=html,
            in_reply_to=original_message_id,
            references=original_message_id,
        )
        logger.info(
            "email_service: sent continue-in-UI to=%s ticket=%s url=%s",
            recipient_email, ticket_number, ticket_url,
        )

    # ── Core delivery ─────────────────────────────────────────────────────────

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
        """
        Build the MIME message, send it, and write a NotificationLog row.

        html_body   — when supplied the message is multipart/alternative
                      (HTML + plain-text fallback); otherwise plain-text only.
        in_reply_to — RFC 2822 In-Reply-To header value (for threading).
        references  — RFC 2822 References header value (for threading).
        """
        now = datetime.now(timezone.utc)
        status = NotificationStatus.PENDING

        try:
            if config["smtp_user"]:
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
                    ),
                )
            else:
                # Dev mode — SMTP not configured, log instead of sending
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
    ) -> None:
        """
        Sync SMTP send — called via run_in_executor so it never blocks the loop.

        Builds a plain-text-only message when html_body is None (existing
        behaviour for all lifecycle notifications).  Builds a
        multipart/alternative message when html_body is supplied (used by
        the two new ingest-pipeline sends so customers receive a styled email).

        Threading headers (In-Reply-To, References) are set when provided so
        outbound messages land in the correct thread in the customer's mail
        client.
        """
        if html_body:
            msg: MIMEMultipart | MIMEText = MIMEMultipart("alternative")
            msg.attach(MIMEText(body, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))
        else:
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(body, "plain"))

        msg["Subject"] = subject
        msg["From"]    = f"{config['smtp_from_name']} <{config['smtp_user']}>"
        msg["To"]      = to

        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references

        with smtplib.SMTP(config["smtp_host"], config["smtp_port"]) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(config["smtp_user"], config["smtp_password"])
            smtp.sendmail(config["smtp_user"], to, msg.as_string())

        logger.info("email_service: sent event to=%s subject=%r", to, subject)