from src.constants.enum import UserRole
from src.core.exceptions.base import InsufficientPermissionsError
from src.core.services.ticket.ticket_base_service import TicketBaseService
from src.data.models.postgres.ticket import Ticket
from src.schemas.ticket_schema import TicketListFilters

class TicketQueryService(TicketBaseService):
    async def get_my_tickets(
        self,
        current_user_id: str,
        current_user_role: str,
        filters: TicketListFilters,
    ) -> tuple[int, list[Ticket]]:
        role = UserRole(current_user_role)
        if role == UserRole.CUSTOMER:
            filters.customer_id = current_user_id
        elif role == UserRole.AGENT:
            filters.assignee_id = current_user_id
        return await self._ticket_repo.list_all(filters)

    async def get_ticket_detail(
        self,
        ticket_id: int,
        current_user_id: str,
        current_user_role: str,
    ) -> Ticket:
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
    ) -> tuple[int, list[Ticket]]:
        role = UserRole(current_user_role)
        if role not in (UserRole.LEAD, UserRole.ADMIN):
            raise InsufficientPermissionsError("Only team leads and admins can view all tickets.")
        return await self._ticket_repo.list_all(filters)
