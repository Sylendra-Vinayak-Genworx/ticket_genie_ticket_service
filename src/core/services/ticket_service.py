import logging
from datetime import datetime, timezone
from src.data.models.postgres.ticket_comment import TicketComment
from src.schemas.ticket_schema import CommentCreateRequest

from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enum import (
    EventType, Priority, Severity, TicketSource, TicketStatus, UserRole,
)
from src.schemas.notification_schema import (
    
    AgentCommentRequest,
    AutoClosedRequest,
    CustomerCommentRequest,
    SLABreachedRequest,
    StatusChangedRequest,
    TicketAssignedRequest,
    TicketCreatedRequest,
)
from src.core.services.notification.manager import notification_manager
from src.core.exceptions.base import (
    InsufficientPermissionsError,
    InvalidStatusTransitionError,
    TicketNotFoundError,
)
from src.core.services.classification_service import ClassificationService
from src.core.services.sla_service import SLAService
from src.data.clients.auth_client import AuthServiceClient, UserDTO
from src.data.models.postgres.ticket import Ticket
from src.data.models.postgres.ticket_attachment import TicketAttachment
from src.data.models.postgres.ticket_event import TicketEvent
from src.data.repositories.keyword_repository import KeywordRepository
from src.data.repositories.sla_repository import SLARepository
from src.data.repositories.sla_rule_repository import SLARuleRepository
from src.data.repositories.ticket_attachment_repository import TicketAttachmentRepository
from src.data.repositories.ticket_event_repository import TicketEventRepository
from src.data.repositories.ticket_repository import TicketRepository
from src.schemas.ticket_schema import (
    TicketAssignRequest,
    TicketCreateRequest,
    TicketListFilters,
    TicketStatusUpdateRequest,
)
from src.data.repositories.ticket_comment_repository import TicketCommentRepository
logger = logging.getLogger(__name__)

# ── Strict transition matrix ──────────────────────────────────────────────────
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


class TicketService:
    def __init__(self, db: AsyncSession, auth_client: AuthServiceClient) -> None:
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
        """
        Write a STATUS_CHANGED TicketEvent row.
        This IS the timeline — filter ticket_events by event_type=STATUS_CHANGED
        to reconstruct the full transition history.
        """
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


    async def create_ticket(
        self,
        payload: TicketCreateRequest,
        current_user_id: str,
    ) -> Ticket:
        """
        Pipeline:
          1. Classify → severity/priority
          2. SLA config lookup
          3. Persist ticket at status=NEW + start response SLA
          4. Log NEW creation in timeline
          5. Auto-transition → ACKNOWLEDGED (SYSTEM)
          6. Send acknowledgement notification
        """
        now = datetime.now(timezone.utc)

        # 1. Fetch user (for tier lookup)
        customer: UserDTO = await self._auth.get_user(current_user_id)

        # 2. Classify
        classification = await self._classifier.classify(payload.title, payload.description)
        severity: Severity = classification.severity
        priority: Priority = classification.priority

        # 3. SLA config
        sla_config = await self._sla_svc.resolve_config(
            customer_tier_id=customer.customer_tier_id,
            severity=severity,
            priority=priority,
        )

        # 4. Build ticket number
        ticket_number = await self._ticket_repo.next_ticket_number()

        # 5. Persist ticket at NEW
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
        )

        self._sla_svc.start_response_sla(ticket, now)

        ticket = await self._ticket_repo.create(ticket)

        await self._record_transition(
            ticket, from_status=None, to_status=TicketStatus.NEW,
            changed_by=current_user_id, reason="Ticket created",
        )

        for url in payload.attachments:
            await self._attachment_repo.add(TicketAttachment(
                ticket_id=ticket.ticket_id,
                file_name=url.split("/")[-1],
                file_url=url,
                uploaded_by_user_id=current_user_id,
            ))

        # 8. Auto-transition → ACKNOWLEDGED (SYSTEM)
        ticket.status = TicketStatus.ACKNOWLEDGED
        ticket = await self._ticket_repo.save(ticket)
        await self._record_transition(
            ticket,
            from_status=TicketStatus.NEW,
            to_status=TicketStatus.ACKNOWLEDGED,
            changed_by=SYSTEM,
            reason="Automatic acknowledgement on creation",
        )

        await notification_manager.send(
            request=TicketCreatedRequest(
                ticket_id=ticket.ticket_id,
                ticket_number=ticket.ticket_number,
                ticket_title=ticket.title,
                customer_id=current_user_id,
            ),
            db=self.db,
            auth_client=self._auth,
        )

        logger.info(
            "ticket_created: number=%s severity=%s priority=%s user=%s",
            ticket_number, severity, priority, current_user_id,
        )
        from src.core.tasks.assignment_task import auto_assign_ticket
        auto_assign_ticket.delay(
            ticket_id=ticket.ticket_id,
            ticket_title=ticket.title
        )
        logger.info(
            "auto_assign_ticket: enqueued for ticket_id=%s", ticket.ticket_id
        )
        return ticket


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

        if UserRole(current_user_role) == UserRole.CUSTOMER:
            if not (old_status == TicketStatus.RESOLVED and new_status == TicketStatus.CLOSED):
                raise InsufficientPermissionsError(
                    "Customers can only close resolved tickets."
                )

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

            await notification_manager.send(
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
                db=self.db,
                auth_client=self._auth,
            )

        logger.info(
            "status_changed: id=%s %s→%s by=%s",
            ticket_id, old_status.value, new_status.value, current_user_id,
        )
        return ticket


    async def assign_ticket(
        self,
        ticket_id: int,
        payload: TicketAssignRequest,
        current_user_id: str,
        current_user_role: str,
    ) -> Ticket:
        ticket = await self._get_or_404(ticket_id)
        role = UserRole(current_user_role)

        if role == UserRole.AGENT and payload.assignee_id != current_user_id:
            raise InsufficientPermissionsError("Agents can only self-assign tickets.")

        old_assignee = ticket.assignee_id
        ticket.assignee_id = payload.assignee_id
        ticket = await self._ticket_repo.save(ticket)

        await self._event_repo.add(TicketEvent(
            ticket_id=ticket.ticket_id,
            triggered_by_user_id=current_user_id,
            event_type=EventType.ASSIGNED,
            field_name="assignee_id",
            old_value=str(old_assignee) if old_assignee else None,
            new_value=payload.assignee_id,
        ))
        await self.transition_status(
            ticket_id=ticket_id,
            payload=TicketStatusUpdateRequest(
                new_status=TicketStatus.OPEN,
                comment="Ticket assigned to agent",
            ),
            current_user_id=current_user_id,
            current_user_role=current_user_role
        )
            
        try:
            customer = await self._auth.get_user(ticket.customer_id)
            customer_name = customer.email.split("@")[0]
        except Exception:
            customer_name = "Customer"

        await notification_manager.send(
            request=TicketAssignedRequest(
                ticket_id=ticket.ticket_id,
                ticket_number=ticket.ticket_number,
                ticket_title=ticket.title,
                severity=ticket.severity.value,
                status=ticket.status.value,
                customer_name=customer_name,
                assignee_id=payload.assignee_id,
            ),
            db=self.db,
            auth_client=self._auth,
        )

        logger.info("assigned: id=%s → %s by %s", ticket_id, payload.assignee_id, current_user_id)
        return ticket


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
            raise TicketNotFoundError(f"Ticket {ticket_id} not found.")
        if UserRole(current_user_role) == UserRole.CUSTOMER and ticket.customer_id != current_user_id:
            raise InsufficientPermissionsError("You can only view your own tickets.")
        return ticket
    

    async def escalate(
        self,
        ticket: Ticket,
        reason: str,
        now: datetime,
    ) -> Ticket:
        
        await self._event_repo.add(TicketEvent(
            ticket_id=ticket.ticket_id,
            triggered_by_user_id=None,                   # SYSTEM-triggered
            event_type=EventType.ESCALATED,
            field_name="escalation_level",
            old_value=str(ticket.escalation_level - 1),  # already incremented by task
            new_value=str(ticket.escalation_level),
            reason=reason,
        ))

        # Resolve the lead for the current assignee
        lead_id: str | None = None
        if ticket.assignee_id:
            try:
                assignee: UserDTO = await self._auth.get_user(ticket.assignee_id)
                lead_id = assignee.lead_id
            except Exception:
                logger.exception(
                    "escalate: failed to fetch assignee user_id=%s for ticket_id=%s",
                    ticket.assignee_id, ticket.ticket_id,
                )

        if not lead_id:
            logger.warning(
                "escalate: ticket_id=%s assignee=%s has no lead_id — "
                "keeping current assignee",
                ticket.ticket_id, ticket.assignee_id,
            )
            return ticket

        if ticket.escalation_level == 1:
            old_assignee = ticket.assignee_id
            ticket.assignee_id = lead_id
            ticket = await self._ticket_repo.save(ticket)

            await self._event_repo.add(TicketEvent(
                ticket_id=ticket.ticket_id,
                triggered_by_user_id=None,
                event_type=EventType.ASSIGNED,
                field_name="assignee_id",
                old_value=str(old_assignee) if old_assignee else None,
                new_value=lead_id,
                reason=f"Escalated to lead after SLA breach (level {ticket.escalation_level})",
            ))

            logger.info(
                "escalated: ticket_id=%s level=%s → lead=%s (assignee's lead)",
                ticket.ticket_id, ticket.escalation_level, lead_id,
            )

        else:
            # Level 2+ — ticket is already with the lead, notify again
            logger.warning(
                "escalated: ticket_id=%s level=%s — lead=%s re-notified, "
                "manual intervention required",
                ticket.ticket_id, ticket.escalation_level, lead_id,
            )

        # Notify the lead — always both email + SSE (operational alert)
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
                breach_type=reason,
                lead_id=lead_id,
            ),
            db=self.db,
            auth_client=self._auth,
        )

        return ticket

    async def get_all_tickets(
        self,
        filters: TicketListFilters,
        current_user_role: str,
        lead_member_ids: list[str] | None = None,
    ) -> tuple[int, list[Ticket]]:
        role = UserRole(current_user_role)
        if role not in (UserRole.LEAD, UserRole.ADMIN):
            raise InsufficientPermissionsError("Only team leads and admins can view all tickets.")
        # Team leads see only their own team's tickets (assignee is them or a team member)
        if role == UserRole.LEAD and lead_member_ids:
            filters = filters.model_copy(update={"assignee_ids": lead_member_ids})
        return await self._ticket_repo.list_all(filters)

    async def add_comment(
        self,
        comment: CommentCreateRequest,
        current_user_id: str,
        current_user_role: str,
    ):
        saved = await self._comment_repo.add(TicketComment(
            ticket_id=comment.ticket_id,
            author_id=current_user_id,
            author_role=current_user_role,
            body=comment.body,
            is_internal=comment.is_internal,
            triggers_hold=comment.triggers_hold,
            triggers_resume=comment.triggers_resume,
        ))

        # Internal notes never trigger notifications
        if comment.is_internal:
            return saved

        ticket = await self._ticket_repo.get_by_id(comment.ticket_id, eager=False)
        if not ticket:
            return saved

        role = UserRole(current_user_role)

        if role == UserRole.CUSTOMER and ticket.assignee_id:
            # Customer replied → notify assigned agent
            await notification_manager.send(
                request=CustomerCommentRequest(
                    ticket_id=ticket.ticket_id,
                    ticket_number=ticket.ticket_number,
                    ticket_title=ticket.title,
                    customer_name=current_user_id,
                    comment_body=comment.body,
                    assignee_id=ticket.assignee_id,
                ),
                db=self.db,
                auth_client=self._auth,
            )

        elif role in (UserRole.AGENT, UserRole.LEAD) and ticket.source == TicketSource.EMAIL:
            # Agent public comment on an EMAIL ticket → AI-drafted reply to customer
            try:
                commenter = await self._auth.get_user(current_user_id)
                agent_name = commenter.email.split("@")[0]
            except Exception:
                agent_name = "Support Agent"

            await notification_manager.send(
                request=AgentCommentRequest(
                    ticket_id=ticket.ticket_id,
                    ticket_number=ticket.ticket_number,
                    ticket_title=ticket.title,
                    status=ticket.status.value,
                    severity=ticket.severity.value,
                    customer_id=ticket.customer_id,
                    agent_name=agent_name,
                    comment_body=comment.body,
                ),
                db=self.db,
                auth_client=self._auth,
            )

        return saved