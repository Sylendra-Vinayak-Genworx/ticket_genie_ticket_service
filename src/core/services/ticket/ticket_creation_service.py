import logging
from datetime import datetime, timezone

from src.constants.enum import Priority, Severity, TicketStatus, QueueType, RoutingStatus
from src.core.services.ticket.ticket_base_service import TicketBaseService, SYSTEM, fire_notification
from src.data.clients.auth_client import UserDTO
from src.data.models.postgres.ticket import Ticket
from src.data.models.postgres.ticket_attachment import TicketAttachment
from src.schemas.notification_schema import TicketCreatedRequest
from src.schemas.ticket_schema import TicketCreateRequest

logger = logging.getLogger(__name__)

class TicketCreationService(TicketBaseService):
    async def create_ticket(
        self,
        payload: TicketCreateRequest,
        current_user_id: str,
    ) -> Ticket:
        """
        Create ticket.
        
        Args:
            payload (TicketCreateRequest): Input parameter.
            current_user_id (str): Input parameter.
        
        Returns:
            Ticket: The expected output.
        """
        now = datetime.now(timezone.utc)
        customer: UserDTO = await self._auth.get_user(current_user_id)
        classification = await self._classifier.classify(
            payload.title,
            payload.description,
            customer_tier_id=customer.customer_tier_id,
        )
        severity: Severity = classification.severity
        priority: Priority = classification.priority


        sla_config = await self._sla_svc.resolve_config(
            customer_tier_id=customer.customer_tier_id,
            severity=severity,
            priority=priority,
        )
        ticket_number = await self._ticket_repo.next_ticket_number()

        ticket = Ticket(
            ticket_number=ticket_number,
            title=payload.title,
            description=payload.description,
            product=payload.product,
            environment=payload.environment,
            source=payload.source,
            area_of_concern=payload.area_of_concern,
            severity=severity,
            priority=priority,
            status=TicketStatus.NEW,
            customer_id=current_user_id,
            customer_tier_id=customer.customer_tier_id,
            response_sla_deadline_minutes=sla_config.response_deadline_minutes,
            resolution_sla_deadline_minutes=sla_config.resolution_deadline_minutes,
            escalation_level=0,
            auto_closed=False,
            team_id=None,
            assignee_id=None,
            queue_type=QueueType.DIRECT.value,
            routing_status=RoutingStatus.SUCCESS.value,
        )

        self._sla_svc.start_response_sla(ticket, now)
        ticket = await self._ticket_repo.create(ticket)

        await self._record_transition(
            ticket, from_status=None, to_status=TicketStatus.NEW,
            changed_by=current_user_id, reason="Ticket created",
        )

        for url in payload.attachments:
            clean = url.split("?")[0]
            if clean.startswith("https://storage.googleapis.com/"):
                parts = clean.split("/", 4)
                blob_path = parts[4] if len(parts) > 4 else clean
            else:
                blob_path = clean

            await self._attachment_repo.add(TicketAttachment(
                ticket_id=ticket.ticket_id,
                file_name=blob_path.split("/")[-1],
                file_url=blob_path,
                uploaded_by_user_id=current_user_id,
            ))

        ticket.status = TicketStatus.ACKNOWLEDGED
        ticket = await self._ticket_repo.save(ticket)
        await self._record_transition(
            ticket,
            from_status=TicketStatus.NEW,
            to_status=TicketStatus.ACKNOWLEDGED,
            changed_by=SYSTEM,
            reason="Automatic acknowledgement on creation",
        )

        await self.db.commit()

        fire_notification(
            request=TicketCreatedRequest(
                ticket_id=ticket.ticket_id,
                ticket_number=ticket.ticket_number,
                ticket_title=ticket.title,
                customer_id=current_user_id,
            ),
            auth_client=self._auth,
        )
        logger.info(
            "ticket_created: number=%s severity=%s priority=%s user=%s",
            ticket_number, severity, priority, current_user_id,
        )
        return ticket
