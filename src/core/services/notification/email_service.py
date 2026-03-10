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


class EmailNotificationService:

    def __init__(self, db: AsyncSession) -> None:
        self._repo = NotificationLogRepository(db)
        s = get_settings()
        self._host      = s.SMTP_HOST
        self._port      = s.SMTP_PORT
        self._user      = s.SMTP_USER
        self._password  = s.SMTP_PASSWORD
        self._from_name = getattr(s, "SMTP_FROM_NAME", "Support Team")


    async def send_ticket_created(
        self, req: TicketCreatedRequest, recipient_email: str
    ) -> None:
        subject = f"[{req.ticket_number}] Your support ticket has been received"
        body = (
            f"Hi,\n\n"
            f"We've received your ticket [{req.ticket_number}]: {req.ticket_title}.\n"
            f"Our team will get back to you shortly.\n\n"
            f"— {self._from_name}"
        )
        await self._deliver(
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
        subject = f"[{req.ticket_number}] New reply from {req.customer_name}"
        body = (
            f"Hi,\n\n"
            f"{req.customer_name} replied on [{req.ticket_number}]: {req.ticket_title}.\n\n"
            f'"{req.comment_body}"\n\n'
            f"Log in to the portal to respond.\n\n"
            f"— {self._from_name}"
        )
        await self._deliver(
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
        subject = f"[{req.ticket_number}] Your ticket has been closed"
        body = (
            f"Hi {customer_name},\n\n"
            f"Your ticket [{req.ticket_number}]: {req.ticket_title} has been "
            f"automatically closed after being resolved with no further activity.\n\n"
            f"If you still need help, please open a new ticket.\n\n"
            f"— {self._from_name}"
        )
        await self._deliver(
            ticket_id=req.ticket_id,
            recipient_id=req.customer_id,
            recipient_email=recipient_email,
            subject=subject,
            body=body,
            event_type="AUTO_CLOSED",
        )

    # ── Core delivery ─────────────────────────────────────────────────────────

    async def _deliver(
        self,
        ticket_id: int,
        recipient_id: str,
        recipient_email: str,
        subject: str,
        body: str,
        event_type: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        status = NotificationStatus.PENDING

        try:
            if self._user:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    partial(
                        self._smtp_send,
                        to=recipient_email,
                        subject=subject,
                        body=body,
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

    def _smtp_send(self, *, to: str, subject: str, body: str) -> None:
        """
        Sync SMTP send — identical pattern to auth service email_service.py.
        Called via run_in_executor so it never blocks the event loop.
        """
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{self._from_name} <{self._user}>"
        msg["To"]      = to

        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(self._host, self._port) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(self._user, self._password)
            smtp.sendmail(self._user, to, msg.as_string())

        logger.info("email_service: sent event to=%s subject=%r", to, subject)