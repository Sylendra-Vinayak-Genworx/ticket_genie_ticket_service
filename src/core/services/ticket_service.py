import asyncio
import logging
from datetime import datetime, timezone
from src.data.models.postgres.ticket_comment import TicketComment
from src.schemas.ticket_schema import CommentCreateRequest

from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enum import (
    EventType, Priority, Severity, TicketSource, TicketStatus, UserRole,
    QueueType, RoutingStatus
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
from src.data.clients.postgres_client import AsyncSessionLocal

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


def _fire_notification(request, auth_client: "AuthServiceClient") -> None:
    """
    Schedule a notification as a fire-and-forget asyncio Task.
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
            # Initialize explicitly before routing
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

        # Store only the blob path (strip signed URL query params if present).
        # Signed URLs are generated fresh on every read — never persisted.
        for url in payload.attachments:
            clean = url.split("?")[0]  # strip query params
            if clean.startswith("https://storage.googleapis.com/"):
                # strip scheme + host + bucket name, leaving just the object path
                parts = clean.split("/", 4)  # ['https:', '', 'storage.googleapis.com', 'bucket', 'object/path']
                blob_path = parts[4] if len(parts) > 4 else clean
            else:
                blob_path = clean

            await self._attachment_repo.add(TicketAttachment(
                ticket_id=ticket.ticket_id,
                file_name=blob_path.split("/")[-1],
                file_url=blob_path,
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

        _fire_notification(
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
        # NOTE: do NOT enqueue auto_assign_ticket here.
        # The session is still open (flushed, not committed). Enqueueing here
        # races the commit — the Celery worker opens its own session and finds
        # the ticket missing.  The route handler enqueues AFTER get_db() commits.
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
            
            # ── Trigger embedding generation (async, non-blocking) ────────────────
            try:
                from src.core.tasks.embedding_tasks import generate_ticket_embedding
                # Pass ticket_id only - task will fetch comments and build solution text
                generate_ticket_embedding.delay(ticket_id=ticket.ticket_id)
                logger.info(
                    "ticket_service: Enqueued embedding generation for resolved ticket_id=%s",
                    ticket.ticket_id
                )
            except Exception as exc:
                # Log error but don't fail the status transition
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

            _fire_notification(
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

        # Only auto-transition ACKNOWLEDGED → OPEN on first assignment.
        # On reassignment the ticket is mid-flight (OPEN / IN_PROGRESS / ON_HOLD),
        # status should not be rewound.
        if ticket.status == TicketStatus.ACKNOWLEDGED:
            await self.transition_status(
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

        # Always notify the new assignee regardless of first assign or reassign
        _fire_notification(
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
        lead_id: str | None = None,
        lead_team_id: str | None = None,
    ) -> Ticket:
        """
        Called by the SLA breach detection task when a response or resolution
        SLA is breached.

        Escalation strategy (FIXED)
        ---------------------------
        The OLD (broken) behaviour was:
            ticket.assignee_id = lead_id
        This caused chaos because:
          - The lead is NOT an agent — they receive alerts and triage, they
            don't work tickets directly.
          - All workload / experience queries against assignee_id became
            polluted with lead user_ids.
          - The lead's own tickets were counted against the lead's "load",
            producing wrong least-loaded calculations.

        The NEW behaviour:
          Level 1  → Route the ticket to the LEAD'S TEAM (team_id = lead_team_id).
                     assignee_id is cleared so any agent in that team can
                     self-claim the ticket.  The lead is notified (SLA alert)
                     but is NEVER written into assignee_id.
          Level 2+ → The ticket is already in the lead's team queue.
                     Notify the lead again and flag for manual intervention.
                     team_id is preserved; no fields are clobbered.

        lead_id and lead_team_id are resolved by the caller (assignment_task.py)
        which has access to Auth Service data.  This method is intentionally
        free of Auth Service calls so it can be called from within a DB
        transaction without risk of network-induced rollbacks.
        """
        # ── Timeline event ────────────────────────────────────────────────────
        await self._event_repo.add(TicketEvent(
            ticket_id=ticket.ticket_id,
            triggered_by_user_id=None,                   # SYSTEM-triggered
            event_type=EventType.ESCALATED,
            field_name="escalation_level",
            old_value=str(ticket.escalation_level - 1),  # already incremented by task
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
            # ── First breach: move ticket into lead's team queue ──────────────
            old_assignee = ticket.assignee_id
            old_team = ticket.team_id

            # Clear individual assignee — the ticket now belongs to the TEAM,
            # not to any specific person.  Any agent in the team can claim it.
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
            # ── Level 2+: already in lead's team queue, notify again ──────────
            logger.warning(
                "escalated: ticket_id=%s level=%s — lead=%s re-notified, "
                "team=%s, manual intervention required.",
                ticket.ticket_id, ticket.escalation_level,
                lead_id, ticket.team_id,
            )

        # ── Notify the lead (always email + SSE) ─────────────────────────────
        try:
            customer = await self._auth.get_user(ticket.customer_id)
            customer_name = customer.email.split("@")[0]
        except Exception:
            customer_name = "Customer"

        _fire_notification(
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

    async def get_all_tickets(
        self,
        filters: TicketListFilters,
        current_user_role: str,
    ) -> tuple[int, list[Ticket]]:
        role = UserRole(current_user_role)
        if role not in (UserRole.LEAD, UserRole.ADMIN):
            raise InsufficientPermissionsError("Only team leads and admins can view all tickets.")
        return await self._ticket_repo.list_all(filters)

    async def add_comment(
        self,
        comment: CommentCreateRequest,
        current_user_id: str,
        current_user_role: str,
    ):
        now = datetime.now(timezone.utc)

        saved = await self._comment_repo.add(TicketComment(
            ticket_id=comment.ticket_id,
            author_id=current_user_id,
            author_role=current_user_role,
            body=comment.body,
            is_internal=comment.is_internal,
            triggers_hold=comment.triggers_hold,
            triggers_resume=comment.triggers_resume,
        ))

        # Persist any images/files uploaded alongside this comment
        for blob_path in (comment.attachments or []):
            clean = blob_path.split("?")[0]  # strip any signed-URL query params
            await self._attachment_repo.add(TicketAttachment(
                ticket_id=comment.ticket_id,
                comment_id=saved.comment_id,   # ← links attachment to this comment
                file_name=clean.split("/")[-1],
                file_url=clean,
                uploaded_by_user_id=current_user_id,
            ))

        # Internal notes never trigger notifications
        if comment.is_internal:
            return saved

        ticket = await self._ticket_repo.get_by_id(comment.ticket_id, eager=False)
        if not ticket:
            return saved

        # ── Act on SLA hold / resume flags ────────────────────────────────────
        if comment.triggers_hold and ticket.status == TicketStatus.IN_PROGRESS:
            self._sla_svc.pause_resolution_sla(ticket, now)
            ticket.status = TicketStatus.ON_HOLD
            ticket = await self._ticket_repo.save(ticket)
            await self._record_transition(
                ticket,
                from_status=TicketStatus.IN_PROGRESS,
                to_status=TicketStatus.ON_HOLD,
                changed_by=current_user_id,
                reason=f"SLA paused via comment: {comment.body[:80]}",
            )
        elif comment.triggers_resume and ticket.status == TicketStatus.ON_HOLD:
            self._sla_svc.resume_resolution_sla(ticket, now)
            ticket.status = TicketStatus.IN_PROGRESS
            ticket = await self._ticket_repo.save(ticket)
            await self._record_transition(
                ticket,
                from_status=TicketStatus.ON_HOLD,
                to_status=TicketStatus.IN_PROGRESS,
                changed_by=current_user_id,
                reason=f"SLA resumed via comment: {comment.body[:80]}",
            )

        role = UserRole(current_user_role)

        if role == UserRole.CUSTOMER and ticket.assignee_id:
            # Customer replied → notify assigned agent
            try:
                customer_user = await self._auth.get_user(current_user_id)
                customer_name = customer_user.email.split("@")[0]
            except Exception:
                customer_name = "Customer"

            _fire_notification(
                request=CustomerCommentRequest(
                    ticket_id=ticket.ticket_id,
                    ticket_number=ticket.ticket_number,
                    ticket_title=ticket.title,
                    customer_name=customer_name,
                    comment_body=comment.body,
                    assignee_id=ticket.assignee_id,
                ),
                auth_client=self._auth,
            )

        elif role in (UserRole.AGENT, UserRole.LEAD, UserRole.ADMIN):
            try:
                commenter = await self._auth.get_user(current_user_id)
                agent_name = commenter.email.split("@")[0]
            except Exception:
                agent_name = "Support Agent"

            if ticket.source == TicketSource.EMAIL:
                _fire_notification(
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
                    auth_client=self._auth,
                )
            else:
                _fire_notification(
                    request=StatusChangedRequest(
                        ticket_id=ticket.ticket_id,
                        ticket_number=ticket.ticket_number,
                        ticket_title=ticket.title,
                        old_status=ticket.status.value,
                        new_status=ticket.status.value,
                        severity=ticket.severity.value,
                        customer_id=ticket.customer_id,
                        agent_name=agent_name,
                    ),
                    auth_client=self._auth,
                )

        return saved
    
    async def self_escalate(
    self,
    ticket_id: int,
    reason: str,
    current_user_id: str,
    current_user_role: str,
) -> Ticket:
        """
        Manual escalation triggered by an agent via the API.
        Replicates the pre-work sla_tasks does before calling escalate(),
        then delegates to the existing escalate() — no logic is duplicated.
        """
        role = UserRole(current_user_role)
        if role != UserRole.AGENT:
            raise InsufficientPermissionsError("Only agents can manually escalate tickets.")

        ticket = await self._get_or_404(ticket_id)
        now = datetime.now(timezone.utc)

        # ── Same pre-work the SLA task does before calling escalate() ────────
        ticket.escalation_level += 1
        ticket.is_escalated = True
        ticket = await self._ticket_repo.save(ticket)

        # ── Resolve lead + team from auth service (same logic as sla_tasks) ──
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

        # ── Delegate entirely to existing escalate() — no logic duplicated ───
        ticket = await self.escalate(
            ticket=ticket,
            reason=reason or f"Manually escalated by agent {current_user_id}",
            now=now,
            lead_id=lead_id,
            lead_team_id=lead_team_id,
        )

        # ── Notify the lead (email + SSE) ─────────────────────────────────────
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