from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enum import Environment, NotificationChannel, TicketSource, UserRole
from src.core.services.classification_service import ClassificationService
from src.core.services.email.email_attachment_service import EmailAttachmentService
from src.core.services.email.email_customer_service import EmailCustomerService
from src.core.services.email.email_parser_service import EmailParserService
from src.core.services.notification.email_service import EmailNotificationService
from src.core.services.notification.manager import notification_manager
from src.core.services.ticket_service import TicketService
from src.data.clients.auth_client import AuthServiceClient
from src.data.clients.postgres_client import AsyncSessionFactory
from src.data.models.postgres.email_thread import EmailDirection, EmailThread
from src.data.models.postgres.ticket_comment import TicketComment
from src.data.models.postgres.ticket_attachment import TicketAttachment
from src.data.repositories.area_of_concern_repository import AreaOfConcernRepository
from src.data.repositories.email_thread_repository import EmailThreadRepository
from src.data.repositories.keyword_repository import KeywordRepository
from src.data.repositories.ticket_attachment_repository import TicketAttachmentRepository
from src.data.repositories.ticket_comment_repository import TicketCommentRepository
from src.data.repositories.ticket_repository import TicketRepository
from src.schemas.email_schema import EmailPayload, EmailTicketParseResult, _groq_async, score_email_quality
from src.schemas.notification_schema import TicketCreatedRequest
from src.schemas.ticket_schema import TicketCreateRequest

logger = logging.getLogger(__name__)

_TICKET_NUM_RE = re.compile(r"\[TKT-(\d+)\]", re.IGNORECASE)


class EmailIngestService:

    def __init__(self, db: AsyncSession, auth_client: AuthServiceClient) -> None:
        """
          init  .
        
        Args:
            db (AsyncSession): Input parameter.
            auth_client (AuthServiceClient): Input parameter.
        """
        self._db = db
        self._auth = auth_client
        self._thread_repo = EmailThreadRepository(db)
        self._ticket_repo = TicketRepository(db)
        self._comment_repo = TicketCommentRepository(db)
        self._attachment_repo = TicketAttachmentRepository(db)
        self._area_repo = AreaOfConcernRepository(db)
        self._ticket_svc = TicketService(db, auth_client)
        self._classifier = ClassificationService(KeywordRepository(db))
        
        self._customer_svc = EmailCustomerService(auth_client)
        self._attachment_svc = EmailAttachmentService()
        self._parser_svc = EmailParserService()

    async def process(self, payload: EmailPayload) -> tuple[int, str] | None:
        """
        Process.
        
        Args:
            payload (EmailPayload): Input parameter.
        
        Returns:
            tuple[int, str] | None: The expected output.
        """
        now = datetime.now(timezone.utc)

        if payload.is_auto_reply:
            logger.info("email_ingest: dropping auto-reply message_id=%s", payload.message_id)
            return None

        if await self._thread_repo.get_by_message_id(payload.message_id):
            logger.info("email_ingest: already processed message_id=%s — skipping", payload.message_id)
            return None

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

    async def _find_existing_ticket(self, payload: EmailPayload) -> int | None:
        def _norm(mid: str) -> str:
            mid = mid.strip().lower()
            if not mid.startswith("<"): mid = f"<{mid}"
            if not mid.endswith(">"): mid = f"{mid}>"
            return mid

        if payload.in_reply_to:
            row = await self._thread_repo.get_by_in_reply_to(_norm(payload.in_reply_to))
            if row: return row.ticket_id

        for ref in payload.references:
            row = await self._thread_repo.get_by_in_reply_to(_norm(ref))
            if row: return row.ticket_id

        m = _TICKET_NUM_RE.search(payload.subject)
        if m:
            ticket_number = f"TKT-{m.group(1).zfill(4)}"
            ticket = await self._ticket_repo.get_by_number(ticket_number)
            if ticket: return ticket.ticket_id

        return None

    async def _create_new_ticket(
        self, payload: EmailPayload, now: datetime
    ) -> tuple[int, str] | None:
        customer, is_new_user, temp_password = await self._customer_svc.resolve_customer(
            payload.sender_email
        )

        areas = await self._area_repo.get_all()

        parsed: EmailTicketParseResult = await _groq_async(
            subject=payload.subject,
            body=payload.body_text or "",
            areas=areas,
        )

        quality = score_email_quality(
            parsed=parsed,
            raw_body=payload.body_text or "",
            raw_subject=payload.subject,
        )
        if not quality.is_sufficient:
            logger.info(
                "email_ingest: insufficient detail message_id=%s missing=%s — sending clarification",
                payload.message_id, quality.missing_fields,
            )
            customer_name = (
                getattr(customer, "full_name", None)
                or payload.sender_email.split("@")[0]
            )
            async with AsyncSessionFactory() as clarify_session:
                await EmailNotificationService(clarify_session).send_clarification_request(
                    recipient_email=payload.sender_email,
                    customer_name=customer_name,
                    original_message_id=payload.message_id,
                    original_subject=payload.subject,
                    missing_fields=quality.missing_fields,
                )
                await clarify_session.commit()
            return None

        classification = await self._classifier.classify(parsed.title, parsed.description)
        parsed.severity = classification.severity.value
        logger.info(
            "email_ingest: classified message_id=%s title=%r product=%r "
            "severity=%r area_name=%r area_id=%s",
            payload.message_id, parsed.title, parsed.product,
            parsed.severity, parsed.area_of_concern_name, parsed.area_of_concern_id,
        )

        attachment_blob_paths = await self._attachment_svc.upload_email_attachments(
            payload, folder=f"tickets/email/{customer.id}"
        )

        ticket = await self._ticket_svc.create_ticket(
            payload=TicketCreateRequest(
                title=parsed.title,
                description=parsed.description,
                product=parsed.product,
                environment=Environment.PROD,
                source=TicketSource.EMAIL,
                area_of_concern=parsed.area_of_concern_id,
                attachments=attachment_blob_paths,
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

        if is_new_user and temp_password:
            await self._customer_svc.send_credentials_email(
                sender_email=payload.sender_email,
                customer_name=customer_name,
                temp_password=temp_password,
                ticket_number=ticket.ticket_number,
                original_message_id=payload.message_id,
                ticket_id=ticket.ticket_id,
                recipient_id=customer.id,
            )

        try:
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
            "email_ingest: created ticket_id=%s number=%s from=%s new_user=%s",
            ticket.ticket_id, ticket.ticket_number,
            payload.sender_email, is_new_user,
        )
        return ticket.ticket_id, ticket.title

    async def _add_reply_comment(
        self, payload: EmailPayload, ticket_id: int, now: datetime
    ) -> None:
        customer, _, _ = await self._customer_svc.resolve_customer(payload.sender_email)
        is_first_reply = await self._thread_repo.count_by_ticket_id(ticket_id) == 1

        clean_body = self._parser_svc.strip_reply_quotes(payload.body_text or payload.subject)

        attachment_blob_paths = await self._attachment_svc.upload_email_attachments(
            payload, folder=f"comments/email/{customer.id}"
        )

        saved_comment = await self._comment_repo.add(TicketComment(
            ticket_id=ticket_id,
            author_id=customer.id,
            author_role=UserRole.CUSTOMER.value,
            body=clean_body,
            is_internal=False,
            triggers_hold=False,
            triggers_resume=False,
        ))

        for blob_path in attachment_blob_paths:
            await self._attachment_repo.add(TicketAttachment(
                ticket_id=ticket_id,
                comment_id=saved_comment.comment_id,
                file_name=blob_path.split("/")[-1],
                file_url=blob_path,
                uploaded_by_user_id=customer.id,
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
            "email_ingest: added comment to ticket_id=%s from=%s first_reply=%s attachments=%d",
            ticket_id, payload.sender_email, is_first_reply, len(attachment_blob_paths),
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
                    "email_ingest: continue-in-UI email failed for ticket_id=%s — comment still saved",
                    ticket_id,
                )

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