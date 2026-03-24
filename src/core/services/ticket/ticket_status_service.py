import logging
from datetime import datetime, timezone

from src.constants.enum import TicketStatus, UserRole, RoutingStatus, EventType
from src.core.exceptions.base import InsufficientPermissionsError, InvalidStatusTransitionError
from src.core.services.ticket.ticket_base_service import TicketBaseService, ALLOWED_TRANSITIONS, SYSTEM, fire_notification
from src.data.models.postgres.ticket import Ticket
from src.data.models.postgres.ticket_event import TicketEvent
from src.schemas.notification_schema import StatusChangedRequest, SLABreachedRequest
from src.schemas.ticket_schema import TicketStatusUpdateRequest

logger = logging.getLogger(__name__)

class TicketStatusService(TicketBaseService):
    async def transition_status(
        self,
        ticket_id: int,
        payload: TicketStatusUpdateRequest,
        current_user_id: str,
        current_user_role: str,
    ) -> Ticket:
        ticket = await self._get_or_404(ticket_id)
        now = datetime.now(timezone.utc)
        old_status = ticket.status
        new_status = payload.new_status

        if UserRole(current_user_role) == UserRole.CUSTOMER and old_status != TicketStatus.RESOLVED:
            raise InsufficientPermissionsError("Customers cannot update ticket status.")

        allowed = ALLOWED_TRANSITIONS.get(old_status, [])
        if new_status not in allowed:
            raise InvalidStatusTransitionError(
                f"Cannot transition {old_status.value} → {new_status.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

        if new_status == TicketStatus.IN_PROGRESS:
            if old_status == TicketStatus.ON_HOLD:
                self._sla_svc.resume_resolution_sla(ticket, now)
            else:
                self._sla_svc.start_resolution_sla(ticket, now)
            self._sla_svc.complete_response_sla(ticket, now)

        elif new_status == TicketStatus.ON_HOLD:
            self._sla_svc.pause_resolution_sla(ticket, now)

        elif new_status == TicketStatus.RESOLVED:
            self._sla_svc.complete_resolution_sla(ticket, now)
            try:
                from src.core.tasks.embedding_tasks import generate_ticket_embedding
                generate_ticket_embedding.delay(ticket_id=ticket.ticket_id)
                logger.info(
                    "ticket_service: Enqueued embedding generation for resolved ticket_id=%s",
                    ticket.ticket_id
                )
            except Exception as exc:
                logger.exception(
                    "ticket_service: Failed to enqueue embedding generation for ticket_id=%s: %s",
                    ticket.ticket_id, exc
                )

        elif new_status == TicketStatus.OPEN and old_status == TicketStatus.CLOSED:
            self._sla_svc.restart_resolution_sla(ticket, now)

        ticket.status = new_status
        ticket = await self._ticket_repo.save(ticket)

        await self._record_transition(
            ticket, from_status=old_status, to_status=new_status,
            changed_by=current_user_id, reason=payload.comment,
        )

        if new_status in (
            TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED,
            TicketStatus.CLOSED, TicketStatus.OPEN,
        ):
            agent_name: str | None = None
            if current_user_id != SYSTEM:
                try:
                    agent = await self._auth.get_user(current_user_id)
                    agent_name = agent.email.split("@")[0]
                except Exception:
                    pass

            fire_notification(
                request=StatusChangedRequest(
                    ticket_id=ticket.ticket_id,
                    ticket_number=ticket.ticket_number,
                    ticket_title=ticket.title,
                    old_status=old_status.value,
                    new_status=new_status.value,
                    severity=ticket.severity.value,
                    customer_id=ticket.customer_id,
                    agent_name=agent_name,
                ),
                auth_client=self._auth,
            )

        logger.info(
            "status_changed: id=%s %s→%s by=%s",
            ticket_id, old_status.value, new_status.value, current_user_id,
        )
        return ticket

    async def escalate(
        self,
        ticket: Ticket,
        reason: str,
        now: datetime,
        lead_id: str | None = None,
        lead_team_id: str | None = None,
    ) -> Ticket:
        await self._event_repo.add(TicketEvent(
            ticket_id=ticket.ticket_id,
            triggered_by_user_id=None,
            event_type=EventType.ESCALATED,
            field_name="escalation_level",
            old_value=str(ticket.escalation_level - 1),
            new_value=str(ticket.escalation_level),
            reason=reason,
        ))

        ticket.routing_status = RoutingStatus.ESCALATED.value

        if not lead_id:
            logger.warning(
                "escalate: ticket_id=%s has no resolvable lead — "
                "ticket remains in current team queue, manual intervention required.",
                ticket.ticket_id,
            )
            return ticket

        if ticket.escalation_level == 1:
            old_assignee = ticket.assignee_id
            old_team = ticket.team_id

            ticket.assignee_id = None
            ticket.team_id = lead_team_id or ticket.team_id

            ticket = await self._ticket_repo.save(ticket)

            await self._event_repo.add(TicketEvent(
                ticket_id=ticket.ticket_id,
                triggered_by_user_id=None,
                event_type=EventType.ASSIGNED,
                field_name="team_id",
                old_value=str(old_team) if old_team else None,
                new_value=str(ticket.team_id) if ticket.team_id else None,
                reason=(
                    f"Escalated to team (lead={lead_id}) after SLA breach "
                    f"(level {ticket.escalation_level}); "
                    f"previous assignee={old_assignee}"
                ),
            ))

            logger.info(
                "escalated: ticket_id=%s level=%s → team=%s (lead=%s notified; "
                "assignee cleared for team self-claim)",
                ticket.ticket_id, ticket.escalation_level,
                ticket.team_id, lead_id,
            )

        else:
            logger.warning(
                "escalated: ticket_id=%s level=%s — lead=%s re-notified, "
                "team=%s, manual intervention required.",
                ticket.ticket_id, ticket.escalation_level,
                lead_id, ticket.team_id,
            )

        try:
            customer = await self._auth.get_user(ticket.customer_id)
            customer_name = customer.email.split("@")[0]
        except Exception:
            customer_name = "Customer"

        fire_notification(
            request=SLABreachedRequest(
                ticket_id=ticket.ticket_id,
                ticket_number=ticket.ticket_number,
                ticket_title=ticket.title,
                severity=ticket.severity.value,
                status=ticket.status.value,
                customer_name=customer_name,
                breach_type=reason,
                lead_id=lead_id,
            ),
            auth_client=self._auth,
        )

        return ticket

    async def self_escalate(
        self,
        ticket_id: int,
        reason: str,
        current_user_id: str,
        current_user_role: str,
    ) -> Ticket:
        from src.core.services.notification.manager import notification_manager
        
        role = UserRole(current_user_role)
        if role != UserRole.AGENT:
            raise InsufficientPermissionsError("Only agents can manually escalate tickets.")

        ticket = await self._get_or_404(ticket_id)
        now = datetime.now(timezone.utc)

        ticket.escalation_level += 1
        ticket.is_escalated = True
        ticket = await self._ticket_repo.save(ticket)

        lead_id: str | None = None
        lead_team_id: str | None = None
        try:
            users = await self._auth.get_all_users()
            leads = [u for u in users if u.role in ("team_lead", "LEAD", "lead")]
            if leads:
                same_team = [u for u in leads if u.team_id == ticket.team_id]
                chosen = same_team[0] if same_team else leads[0]
                lead_id = chosen.id
                lead_team_id = chosen.team_id
        except Exception:
            logger.warning("self_escalate: could not resolve lead for ticket_id=%s", ticket_id)

        ticket = await self.escalate(
            ticket=ticket,
            reason=reason or f"Manually escalated by agent {current_user_id}",
            now=now,
            lead_id=lead_id,
            lead_team_id=lead_team_id,
        )

        if lead_id:
            try:
                customer = await self._auth.get_user(ticket.customer_id)
                customer_name = customer.email.split("@")[0]
            except Exception:
                customer_name = "Customer"

            await notification_manager.send(
                request=SLABreachedRequest(
                    ticket_id=ticket.ticket_id,
                    ticket_number=ticket.ticket_number,
                    ticket_title=ticket.title,
                    severity=ticket.severity.value,
                    status=ticket.status.value,
                    customer_name=customer_name,
                    breach_type=reason or f"Manually escalated by agent {current_user_id}",
                    lead_id=lead_id,
                ),
                db=self.db,
                auth_client=self._auth,
            )

        return ticket
