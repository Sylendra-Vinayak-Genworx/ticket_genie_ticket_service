from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.clients.auth_client import AuthServiceClient
from src.data.models.postgres.ticket import Ticket
from src.schemas.ticket_schema import (
    CommentCreateRequest, TicketAssignRequest, TicketCreateRequest, 
    TicketListFilters, TicketStatusUpdateRequest
)

from src.core.services.ticket.ticket_creation_service import TicketCreationService
from src.core.services.ticket.ticket_status_service import TicketStatusService
from src.core.services.ticket.ticket_assignment_service import TicketAssignmentService
from src.core.services.ticket.ticket_query_service import TicketQueryService
from src.core.services.ticket.ticket_comment_service import TicketCommentService


class TicketService:
    """
    Facade class that delegates complex domain operations to specialized 
    sub-services, keeping the interface backward compatible for controllers.
    """
    def __init__(self, db: AsyncSession, auth_client: AuthServiceClient) -> None:
        self.db = db
        self._auth = auth_client
        
        self.creation_svc = TicketCreationService(db, auth_client)
        self.status_svc = TicketStatusService(db, auth_client)
        self.assignment_svc = TicketAssignmentService(db, auth_client)
        self.query_svc = TicketQueryService(db, auth_client)
        self.comment_svc = TicketCommentService(db, auth_client)

    async def create_ticket(self, payload: TicketCreateRequest, current_user_id: str) -> Ticket:
        return await self.creation_svc.create_ticket(payload, current_user_id)

    async def transition_status(
        self, ticket_id: int, payload: TicketStatusUpdateRequest,
        current_user_id: str, current_user_role: str
    ) -> Ticket:
        return await self.status_svc.transition_status(ticket_id, payload, current_user_id, current_user_role)

    async def assign_ticket(
        self, ticket_id: int, payload: TicketAssignRequest,
        current_user_id: str, current_user_role: str, team_id: str | None = None
    ) -> Ticket:
        return await self.assignment_svc.assign_ticket(ticket_id, payload, current_user_id, current_user_role, team_id)

    async def get_my_tickets(
        self, current_user_id: str, current_user_role: str, filters: TicketListFilters
    ) -> tuple[int, list[Ticket]]:
        return await self.query_svc.get_my_tickets(current_user_id, current_user_role, filters)

    async def get_ticket_detail(
        self, ticket_id: int, current_user_id: str, current_user_role: str
    ) -> Ticket:
        return await self.query_svc.get_ticket_detail(ticket_id, current_user_id, current_user_role)

    async def escalate(
        self, ticket: Ticket, reason: str, now: datetime,
        lead_id: str | None = None, lead_team_id: str | None = None
    ) -> Ticket:
        return await self.status_svc.escalate(ticket, reason, now, lead_id, lead_team_id)

    async def get_all_tickets(
        self, filters: TicketListFilters, current_user_role: str
    ) -> tuple[int, list[Ticket]]:
        return await self.query_svc.get_all_tickets(filters, current_user_role)

    async def add_comment(
        self, comment: CommentCreateRequest, current_user_id: str, current_user_role: str
    ):
        return await self.comment_svc.add_comment(comment, current_user_id, current_user_role)

    async def self_escalate(
        self, ticket_id: int, reason: str, current_user_id: str, current_user_role: str
    ) -> Ticket:
        return await self.status_svc.self_escalate(ticket_id, reason, current_user_id, current_user_role)