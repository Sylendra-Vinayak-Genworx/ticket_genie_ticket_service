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
        """
          init  .
        
        Args:
            db (AsyncSession): Input parameter.
            auth_client (AuthServiceClient): Input parameter.
        """
        self.db = db
        self._auth = auth_client
        
        self.creation_svc = TicketCreationService(db, auth_client)
        self.status_svc = TicketStatusService(db, auth_client)
        self.assignment_svc = TicketAssignmentService(db, auth_client)
        self.query_svc = TicketQueryService(db, auth_client)
        self.comment_svc = TicketCommentService(db, auth_client)

    async def create_ticket(self, payload: TicketCreateRequest, current_user_id: str) -> Ticket:
        """
        Create ticket.
        
        Args:
            payload (TicketCreateRequest): Input parameter.
            current_user_id (str): Input parameter.
        
        Returns:
            Ticket: The expected output.
        """
        return await self.creation_svc.create_ticket(payload, current_user_id)

    async def transition_status(
        self, ticket_id: int, payload: TicketStatusUpdateRequest,
        current_user_id: str, current_user_role: str
    ) -> Ticket:
        """
        Transition status.
        
        Args:
            ticket_id (int): Input parameter.
            payload (TicketStatusUpdateRequest): Input parameter.
            current_user_id (str): Input parameter.
            current_user_role (str): Input parameter.
        
        Returns:
            Ticket: The expected output.
        """
        return await self.status_svc.transition_status(ticket_id, payload, current_user_id, current_user_role)

    async def assign_ticket(
        self, ticket_id: int, payload: TicketAssignRequest,
        current_user_id: str, current_user_role: str, team_id: str | None = None
    ) -> Ticket:
        """
        Assign ticket.
        
        Args:
            ticket_id (int): Input parameter.
            payload (TicketAssignRequest): Input parameter.
            current_user_id (str): Input parameter.
            current_user_role (str): Input parameter.
            team_id (str | None): Input parameter.
        
        Returns:
            Ticket: The expected output.
        """
        return await self.assignment_svc.assign_ticket(ticket_id, payload, current_user_id, current_user_role, team_id)

    async def get_my_tickets(
        self, filters: TicketListFilters, current_user_role: str, current_user_id: str
    ) -> tuple[int, list[Ticket]]:
        """
        Get my tickets.
        
        Args:
            filters (TicketListFilters): Input parameter.
            current_user_role (str): Input parameter.
            current_user_id (str): Input parameter.
        
        Returns:
            tuple[int, list[Ticket]]: The expected output.
        """
        return await self.query_svc.get_my_tickets(filters, current_user_role, current_user_id)

    async def get_ticket_detail(
        self, ticket_id: int, current_user_id: str, current_user_role: str
    ) -> Ticket:
        """
        Get ticket detail.
        
        Args:
            ticket_id (int): Input parameter.
            current_user_id (str): Input parameter.
            current_user_role (str): Input parameter.
        
        Returns:
            Ticket: The expected output.
        """
        return await self.query_svc.get_ticket_detail(ticket_id, current_user_id, current_user_role)

    async def escalate(
        self, ticket: Ticket, reason: str, now: datetime,
        lead_id: str | None = None, lead_team_id: str | None = None
    ) -> Ticket:
        """
        Escalate.
        
        Args:
            ticket (Ticket): Input parameter.
            reason (str): Input parameter.
            now (datetime): Input parameter.
            lead_id (str | None): Input parameter.
            lead_team_id (str | None): Input parameter.
        
        Returns:
            Ticket: The expected output.
        """
        return await self.status_svc.escalate(ticket, reason, now, lead_id, lead_team_id)

    async def get_all_tickets(
        self, filters: TicketListFilters, current_user_role: str, current_user_id: str
    ) -> tuple[int, list[Ticket]]:
        """
        Get all tickets.
        
        Args:
            filters (TicketListFilters): Input parameter.
            current_user_role (str): Input parameter.
            current_user_id (str): Input parameter.
        
        Returns:
            tuple[int, list[Ticket]]: The expected output.
        """
        return await self.query_svc.get_all_tickets(filters, current_user_role, current_user_id)

    async def get_team_kpis(
        self, filters: TicketListFilters, current_user_role: str, current_user_id: str
    ) -> dict[str, int]:
        """
        Calculates Key Performance Indicators (KPIs) (active, breached, unclaimed, resolved) 
        given a basic set of team/assignee filters.
        """
        return await self.query_svc.get_team_kpis(filters, current_user_role, current_user_id)

    async def add_comment(
        self, comment: CommentCreateRequest, current_user_id: str, current_user_role: str
    ):
        """
        Add comment.
        
        Args:
            comment (CommentCreateRequest): Input parameter.
            current_user_id (str): Input parameter.
            current_user_role (str): Input parameter.
        """
        return await self.comment_svc.add_comment(comment, current_user_id, current_user_role)

    async def self_escalate(
        self, ticket_id: int, reason: str, current_user_id: str, current_user_role: str
    ) -> Ticket:
        """
        Self escalate.
        
        Args:
            ticket_id (int): Input parameter.
            reason (str): Input parameter.
            current_user_id (str): Input parameter.
            current_user_role (str): Input parameter.
        
        Returns:
            Ticket: The expected output.
        """
        return await self.status_svc.self_escalate(ticket_id, reason, current_user_id, current_user_role)

    def enqueue_auto_assign(self, ticket_id: int, ticket_title: str) -> None:
        """Enqueue the auto-assignment Celery task."""
        import logging
        from src.core.tasks.assignment_task import auto_assign_ticket
        auto_assign_ticket.delay(ticket_id=ticket_id, ticket_title=ticket_title)
        logging.getLogger(__name__).info(
            "auto_assign_ticket: enqueued post-auth for ticket_id=%s", ticket_id
        )