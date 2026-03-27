import asyncio
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from src.constants.enum import EventType, TicketStatus
from src.core.exceptions.base import TicketNotFoundError
from src.core.services.notification.manager import notification_manager
from src.data.clients.auth_client import AuthServiceClient
from src.data.clients.postgres_client import AsyncSessionLocal
from src.data.models.postgres.ticket import Ticket
from src.data.models.postgres.ticket_event import TicketEvent
from src.data.repositories.area_of_concern_repository import AreaOfConcernRepository
from src.data.repositories.keyword_repository import KeywordRepository
from src.data.repositories.sla_repository import SLARepository
from src.data.repositories.sla_rule_repository import SLARuleRepository
from src.data.repositories.ticket_attachment_repository import TicketAttachmentRepository
from src.data.repositories.ticket_comment_repository import TicketCommentRepository
from src.data.repositories.ticket_event_repository import TicketEventRepository
from src.data.repositories.ticket_repository import TicketRepository
from src.core.services.classification_service import ClassificationService
from src.core.services.sla_service import SLAService

logger = logging.getLogger(__name__)

ALLOWED_TRANSITIONS: dict[TicketStatus, list[TicketStatus]] = {
    TicketStatus.NEW:          [TicketStatus.ACKNOWLEDGED],
    TicketStatus.ACKNOWLEDGED: [TicketStatus.OPEN],
    TicketStatus.OPEN:         [TicketStatus.IN_PROGRESS],
    TicketStatus.IN_PROGRESS:  [TicketStatus.ON_HOLD, TicketStatus.RESOLVED],
    TicketStatus.ON_HOLD:      [TicketStatus.IN_PROGRESS],
    TicketStatus.RESOLVED:     [TicketStatus.CLOSED],
    TicketStatus.CLOSED:       [TicketStatus.OPEN],   # reopen
}

SYSTEM = "SYSTEM"


def fire_notification(request, auth_client: "AuthServiceClient") -> None:
    """
    Fire notification.
    
    Args:
        request (Any): Input parameter.
        auth_client ('AuthServiceClient'): Input parameter.
    """
    async def _run():
        async with AsyncSessionLocal() as db:
            try:
                await notification_manager.send(
                    request=request,
                    db=db,
                    auth_client=auth_client,
                )
                await db.commit()
            except Exception:
                await db.rollback()
                import logging as _log
                _log.getLogger(__name__).exception(
                    "_fire_notification: task failed for type=%s", request.type
                )
    asyncio.create_task(_run())


class TicketBaseService:
    def __init__(self, db: AsyncSession, auth_client: AuthServiceClient) -> None:
        """
          init  .
        
        Args:
            db (AsyncSession): Input parameter.
            auth_client (AuthServiceClient): Input parameter.
        """
        self.db = db
        self._auth = auth_client
        self._ticket_repo = TicketRepository(db)
        self._event_repo = TicketEventRepository(db)
        self._attachment_repo = TicketAttachmentRepository(db)
        self._sla_repo = SLARepository(db)
        self._sla_rule_repo = SLARuleRepository(db)
        self._keyword_repo = KeywordRepository(db)
        self._comment_repo = TicketCommentRepository(db)
        self._classifier = ClassificationService(self._keyword_repo)
        self._sla_svc = SLAService(self._sla_repo, self._sla_rule_repo)

    async def _get_or_404(self, ticket_id: int) -> Ticket:
        ticket = await self._ticket_repo.get_by_id(ticket_id)
        if not ticket:
            raise TicketNotFoundError(f"Ticket {ticket_id} not found.")
        return ticket

    async def _record_transition(
        self,
        ticket: Ticket,
        from_status: TicketStatus | None,
        to_status: TicketStatus,
        changed_by: str,
        reason: str | None = None,
    ) -> None:
        await self._event_repo.add(TicketEvent(
            ticket_id=ticket.ticket_id,
            triggered_by_user_id=changed_by if changed_by != "SYSTEM" else None,
            event_type=EventType.STATUS_CHANGED,
            field_name="status",
            from_status=from_status.value if from_status else None,
            old_value=from_status.value if from_status else None,
            new_value=to_status.value,
            reason=reason,
        ))
