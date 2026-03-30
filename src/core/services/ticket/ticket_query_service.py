import logging
from src.constants.enum import UserRole
from src.core.exceptions.base import InsufficientPermissionsError
from src.core.services.ticket.ticket_base_service import TicketBaseService
from src.data.models.postgres.ticket import Ticket
from src.schemas.ticket_schema import TicketListFilters

logger = logging.getLogger(__name__)

class TicketQueryService(TicketBaseService):
    async def get_my_tickets(
        self,
        filters: TicketListFilters,
        current_user_role: str,
        current_user_id: str,
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
        role = UserRole(current_user_role)
        if role == UserRole.CUSTOMER:
            filters.customer_id = current_user_id
        elif role == UserRole.AGENT:
            filters.assignee_id = current_user_id
        elif role == UserRole.LEAD:
            filters.team_id = current_user_id
        return await self._ticket_repo.list_all(filters)

    async def get_ticket_detail(
        self,
        ticket_id: int,
        current_user_id: str,
        current_user_role: str,
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
        ticket = await self._ticket_repo.get_by_id(ticket_id, eager=True)
        if not ticket:
            from src.core.exceptions.base import TicketNotFoundError
            raise TicketNotFoundError(f"Ticket {ticket_id} not found.")
        if UserRole(current_user_role) == UserRole.CUSTOMER and ticket.customer_id != current_user_id:
            raise InsufficientPermissionsError("You can only view your own tickets.")
        return ticket

    async def get_all_tickets(
        self,
        filters: TicketListFilters,
        current_user_role: str,
        current_user_id: str,
    ) -> tuple[int, list[Ticket]]:
        """
        Get all tickets (scoped to team if LEAD).
        """
        role = UserRole(current_user_role)
        if role not in (UserRole.LEAD, UserRole.ADMIN):
            raise InsufficientPermissionsError("Only team leads and admins can view all tickets.")
        
        if role == UserRole.LEAD:
            # Resolve team member IDs (lead + anyone reporting to them)
            # This ensures we see all tickets assigned to the team.
            try:
                all_users = await self._auth.get_all_users()
                members = [
                    u.id for u in all_users
                    if u.lead_id == current_user_id or u.id == current_user_id
                ]
                filters.assignee_ids = members if members else [current_user_id]
                # Also try to resolve a proper team_id if available on the lead's profile
                lead_user = next((u for u in all_users if u.id == current_user_id), None)
                if lead_user and lead_user.team_id:
                    filters.team_id = lead_user.team_id
                else:
                    filters.team_id = None # Clear any incorrect ID
            except Exception as exc:
                logger.error("Failed to resolve team members: %s", exc)
                filters.assignee_ids = [current_user_id]

        return await self._ticket_repo.list_all(filters)
        
    async def get_team_kpis(
        self,
        filters: TicketListFilters,
        current_user_role: str,
        current_user_id: str,
    ) -> dict[str, int]:
        """
        Get team ticket KPIs (scoped to team if LEAD).
        """
        role = UserRole(current_user_role)
        if role not in (UserRole.LEAD, UserRole.ADMIN):
            raise InsufficientPermissionsError("Only team leads and admins can view team KPIs.")
            
        if role == UserRole.LEAD:
            # Consistent with list_all: resolve scope by member IDs + team ID
            try:
                all_users = await self._auth.get_all_users()
                members = [
                    u.id for u in all_users
                    if u.lead_id == current_user_id or u.id == current_user_id
                ]
                filters.assignee_ids = members if members else [current_user_id]
                lead_user = next((u for u in all_users if u.id == current_user_id), None)
                if lead_user and lead_user.team_id:
                    filters.team_id = lead_user.team_id
                else:
                    filters.team_id = None
            except Exception as exc:
                logger.error("Failed to resolve team members for KPIs: %s", exc)
                filters.assignee_ids = [current_user_id]
        
        return await self._ticket_repo.get_team_kpis(filters)
