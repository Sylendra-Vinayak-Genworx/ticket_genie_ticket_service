import logging
from src.constants.enum import UserRole, QueueType, RoutingStatus, TicketStatus, EventType
from src.core.exceptions.base import InsufficientPermissionsError
from src.core.services.ticket.ticket_base_service import TicketBaseService, fire_notification
from src.data.models.postgres.ticket import Ticket
from src.data.models.postgres.ticket_event import TicketEvent
from src.schemas.notification_schema import TicketAssignedRequest
from src.schemas.ticket_schema import TicketAssignRequest, TicketStatusUpdateRequest

logger = logging.getLogger(__name__)

class TicketAssignmentService(TicketBaseService):
    async def assign_ticket(
        self,
        ticket_id: int,
        payload: TicketAssignRequest,
        current_user_id: str,
        current_user_role: str,
        team_id: str | None = None,
    ) -> Ticket:
        ticket = await self._get_or_404(ticket_id)
        role = UserRole(current_user_role)

        if role == UserRole.AGENT and payload.assignee_id != current_user_id:
            raise InsufficientPermissionsError("Agents can only self-assign tickets.")

        old_assignee = ticket.assignee_id
        is_reassignment = old_assignee is not None

        if payload.assignee_id:
            ticket.assignee_id = payload.assignee_id
            ticket.queue_type = QueueType.DIRECT.value
            ticket.routing_status = RoutingStatus.SUCCESS.value

            if ticket.is_escalated:
                ticket.is_escalated = False
                ticket.escalation_level = 0

        resolved_team_id = team_id
        if resolved_team_id is not None:
            ticket.team_id = resolved_team_id

        ticket = await self._ticket_repo.save(ticket)

        await self._event_repo.add(TicketEvent(
            ticket_id=ticket.ticket_id,
            triggered_by_user_id=current_user_id,
            event_type=EventType.ASSIGNED,
            field_name="assignee_id",
            old_value=str(old_assignee) if old_assignee else None,
            new_value=ticket.assignee_id or f"team:{ticket.team_id}",
            reason="Reassigned to new agent" if is_reassignment else "Initial assignment",
        ))

        if ticket.status == TicketStatus.ACKNOWLEDGED:
            from src.core.services.ticket.ticket_status_service import TicketStatusService
            status_svc = TicketStatusService(self.db, self._auth)
            await status_svc.transition_status(
                ticket_id=ticket_id,
                payload=TicketStatusUpdateRequest(
                    new_status=TicketStatus.OPEN,
                    comment="Ticket assigned to agent",
                ),
                current_user_id=current_user_id,
                current_user_role=current_user_role,
            )

        try:
            customer = await self._auth.get_user(ticket.customer_id)
            customer_name = customer.email.split("@")[0]
        except Exception:
            customer_name = "Customer"

        fire_notification(
            request=TicketAssignedRequest(
                ticket_id=ticket.ticket_id,
                ticket_number=ticket.ticket_number,
                ticket_title=ticket.title,
                severity=ticket.severity.value,
                status=ticket.status.value,
                customer_name=customer_name,
                assignee_id=ticket.assignee_id or "",
            ),
            auth_client=self._auth,
        )

        logger.info(
            "%s: id=%s → assignee=%s (was %s) team=%s by %s",
            "reassigned" if is_reassignment else "assigned",
            ticket_id, ticket.assignee_id, old_assignee, ticket.team_id, current_user_id,
        )
        return ticket
