"""
src/core/tasks/assignment_task.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Auto-assignment Celery task.

Routing pipeline
----------------
1. Run AutoAssignmentService: score agents by experience / (1 + workload) for
   the ticket's area_of_concern, fall back to least-loaded agent globally.
   The service writes assignee_id (agent) AND team_id.

2. If no agent found → fallback to least-loaded LEAD (via Auth Service).
   The lead is NOTIFIED but never written into assignee_id.
   Instead, ticket.team_id is set to the lead's team_id so the ticket
   appears in the correct team queue for any agent to self-claim.
   ticket.assignee_id remains NULL.

3. If no lead available → move ticket to OPEN queue (team_id = NULL).

4. Beat job `check_lead_timeout` watches AI_FAILED tickets and moves them
   to the OPEN queue when no agent self-claimed within the timeout window.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from src.celery_app import celery_app
from src.config.settings import get_settings
from src.constants.enum import EventType, QueueType, RoutingStatus, TicketStatus
from src.core.tasks._loop import run_async
from src.core.services.auto_assignement_service import AutoAssignmentService
from src.data.clients.auth_client import auth_client
from src.data.clients.postgres_client import AsyncSessionFactory
from src.data.models.postgres.ticket_event import TicketEvent
from src.data.repositories.ticket_event_repository import TicketEventRepository
from src.data.repositories.ticket_repository import TicketRepository
from src.data.repositories.ticket_assignment_repositoty import TicketAssignmentRepository

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Score-based agent assignment
# ─────────────────────────────────────────────────────────────────────────────

async def _score_assign_ticket(ticket_id: int) -> bool:
    """
    Delegate to AutoAssignmentService (experience / workload score).

    Returns True  → an agent was assigned (assignee_id + team_id stamped).
    Returns False → no agent found; caller should invoke _fallback_to_lead.
    """
    async with AsyncSessionFactory() as session:
        ticket_repo = TicketRepository(session)

        ticket = await ticket_repo.get_by_id(ticket_id, eager=False)

        if not ticket:
            logger.error("[ticket=%s] Not found — aborting", ticket_id)
            return False

        if ticket.routing_status == RoutingStatus.SUCCESS.value and ticket.assignee_id:
            logger.info("[ticket=%s] Already routed — skipping", ticket_id)
            return True

        svc = AutoAssignmentService(session)
        result = await svc.assign(
            ticket_id=ticket_id,
            area_of_concern=ticket.area_of_concern,
        )

        if result.assigned_to:
            # assign_ticket() already flushed assignee_id + team_id.
            # Stamp routing_status + queue_type now.
            refreshed = await ticket_repo.get_by_id(ticket_id, eager=False)
            if refreshed:
                refreshed.routing_status = RoutingStatus.SUCCESS.value
                refreshed.queue_type = QueueType.DIRECT.value
                session.add(refreshed)
            await session.commit()
            logger.info(
                "[ticket=%s] Score-based routing SUCCESS → agent=%s team=%s "
                "(strategy=%s, score=%s)",
                ticket_id, result.assigned_to, result.team_id,
                result.strategy, result.score,
            )
            return True

        logger.info(
            "[ticket=%s] AutoAssignmentService found no agent (strategy=%s)",
            ticket_id, result.strategy,
        )
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Fallback: least-loaded lead  (team-based, NOT assignee_id)
# ─────────────────────────────────────────────────────────────────────────────

async def _fallback_to_lead(ticket_id: int) -> None:
    """
    Fallback when score-based routing fails.

    Strategy (FIXED)
    ----------------
    OLD (broken): ticket.assignee_id = lead_id
        → Pollutes workload queries, lead receives all agent work.

    NEW (correct):
    1. Fetch all users from Auth Service.
    2. Filter role == LEAD users, collect their user_id AND team_id.
    3. Select least-loaded lead by active ticket count (via assignment repo).
    4. Set ticket.team_id = lead.team_id  (ticket enters the team queue).
       ticket.assignee_id remains NULL — any agent in the team can self-claim.
    5. Set routing_status = AI_FAILED so the beat job can watch it.
    6. If no lead available → OPEN queue.
    """
    now = datetime.now(timezone.utc)

    async with AsyncSessionFactory() as session:
        ticket_repo = TicketRepository(session)
        event_repo = TicketEventRepository(session)
        assignment_repo = TicketAssignmentRepository(session)

        ticket = await ticket_repo.get_by_id(ticket_id, eager=False)

        if not ticket:
            logger.error("[ticket=%s] ticket not found", ticket_id)
            return

        if ticket.assignee_id:
            logger.info("[ticket=%s] already assigned to agent — skipping fallback", ticket_id)
            return

        lead_id: str | None = None
        lead_team_id: str | None = None

        try:
            users = await auth_client.get_all_users()
            if not users:
                raise ValueError("No users returned from auth service")

            # Extract leads with their team_id — never infer role from ticket data
            leads = [u for u in users if u.role in ("team_lead", "LEAD", "lead")]
            if not leads:
                raise ValueError("No lead users found in auth service")

            lead_ids = [u.id for u in leads]
            lead_team_map = {u.id: u.team_id for u in leads}

            # Use assignment repo to pick least-loaded lead, preferring same team
            chosen_lead_id = await assignment_repo.get_least_loaded_lead_for_team(
                lead_ids=lead_ids,
                team_id=ticket.team_id,
            )
            lead_id = chosen_lead_id
            lead_team_id = lead_team_map.get(chosen_lead_id) if chosen_lead_id else None

            logger.info(
                "[ticket=%s] fallback → lead=%s team=%s",
                ticket_id, lead_id, lead_team_id,
            )

        except Exception:
            logger.exception(
                "[ticket=%s] failed to resolve lead — moving to OPEN queue",
                ticket_id,
            )
            # Transaction might be aborted by Postgres if query failed. Rollback and refetch.
            await session.rollback()
            ticket = await ticket_repo.get_by_id(ticket_id, eager=False)
            if not ticket:
                return

        ticket.routing_status = RoutingStatus.AI_FAILED.value
        ticket.fallback_assigned_at = now

        if lead_id:
            # Route to the LEAD'S TEAM — assignee_id stays NULL
            ticket.team_id = lead_team_id or ticket.team_id
            ticket.queue_type = QueueType.DIRECT.value
            # assignee_id intentionally NOT set here

            await event_repo.add(
                TicketEvent(
                    ticket_id=ticket.ticket_id,
                    triggered_by_user_id=None,
                    event_type=EventType.ASSIGNED,
                    field_name="team_id",
                    old_value=None,
                    new_value=lead_team_id,
                    reason=(
                        f"AI routing failed — routed to team of lead={lead_id}; "
                        "assignee_id left NULL for team self-claim"
                    ),
                )
            )

            logger.info(
                "[ticket=%s] fallback: team_id=%s (lead=%s notified, assignee=NULL)",
                ticket_id, lead_team_id, lead_id,
            )

        else:
            # Genuinely no lead — dump to open queue
            ticket.assignee_id = None
            ticket.team_id = None
            ticket.queue_type = QueueType.OPEN.value

            await event_repo.add(
                TicketEvent(
                    ticket_id=ticket.ticket_id,
                    triggered_by_user_id=None,
                    event_type=EventType.ASSIGNED,
                    field_name="queue_type",
                    old_value=None,
                    new_value=QueueType.OPEN.value,
                    reason="AI routing failed and no lead available — moved to OPEN queue",
                )
            )

            logger.warning("[ticket=%s] moved to OPEN queue (no lead available)", ticket_id)

        await ticket_repo.save(ticket)
        await session.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — Timeout: move unclaimed fallback tickets to OPEN queue
# ─────────────────────────────────────────────────────────────────────────────

async def _move_to_open_queue(ticket_id: int) -> None:
    """Move a fallback-assigned ticket to the OPEN queue after the timeout."""
    async with AsyncSessionFactory() as session:
        ticket_repo = TicketRepository(session)
        event_repo = TicketEventRepository(session)

        ticket = await ticket_repo.get_by_id(ticket_id, eager=False)

        if not ticket:
            logger.warning("[ticket=%s] _move_to_open_queue: ticket not found", ticket_id)
            return

        old_team = ticket.team_id

        ticket.assignee_id = None
        ticket.team_id = None
        ticket.queue_type = QueueType.OPEN.value
        ticket.routing_status = RoutingStatus.AI_FAILED.value
        ticket.status = TicketStatus.OPEN

        await ticket_repo.save(ticket)

        await event_repo.add(TicketEvent(
            ticket_id=ticket.ticket_id,
            triggered_by_user_id=None,
            event_type=EventType.STATUS_CHANGED,
            field_name="status",
            old_value=TicketStatus.ACKNOWLEDGED.value,
            new_value=TicketStatus.OPEN.value,
            reason=(
                f"Fallback team '{old_team}' did not self-claim within the timeout window "
                "— moved to OPEN queue"
            ),
        ))

        await session.commit()

        logger.info(
            "[ticket=%s] Moved to OPEN queue (team=%s timed out)",
            ticket_id, old_team,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Celery tasks
# ─────────────────────────────────────────────────────────────────────────────

@celery_app.task(
    name="tasks.auto_assign_ticket",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
    reject_on_worker_lost=True,
)
def auto_assign_ticket(self, ticket_id: int, ticket_title: str):
    """
    Main routing task — called once per ticket after creation.

    Flow
    ----
    score_assign  →  SUCCESS  → done (assignee_id + team_id set)
         ↓ False / exception
    fallback_to_lead  →  team_id set, assignee_id = NULL, beat job watches
                      →  no lead → OPEN queue
    """
    logger.info(
        "[ticket=%s] auto_assign_ticket started (attempt=%d/%d)",
        ticket_id, self.request.retries + 1, self.max_retries + 1,
    )

    try:
        success = run_async(_score_assign_ticket(ticket_id))
    except Exception as exc:
        logger.exception("[ticket=%s] Score-based assignment raised — triggering fallback", ticket_id)
        try:
            run_async(_fallback_to_lead(ticket_id))
        except Exception:
            logger.exception("[ticket=%s] Fallback also failed", ticket_id)
            raise self.retry(exc=exc, countdown=30 * 2 ** self.request.retries)
        
        # Fallback executed successfully, so we do NOT retry the whole task
        return {
            "ticket_id": ticket_id,
            "routing_status": RoutingStatus.AI_FAILED.value,
            "message": "Score routing raised exception — routed to lead team queue via fallback",
        }

    if success:
        return {
            "ticket_id": ticket_id,
            "routing_status": RoutingStatus.SUCCESS.value,
            "message": "Assigned via experience/workload score routing",
        }

    try:
        run_async(_fallback_to_lead(ticket_id))
    except Exception as exc:
        logger.exception("[ticket=%s] Fallback to lead failed", ticket_id)
        raise self.retry(exc=exc, countdown=30 * 2 ** self.request.retries)

    return {
        "ticket_id": ticket_id,
        "routing_status": RoutingStatus.AI_FAILED.value,
        "message": "Score routing found no agent — routed to lead team queue (assignee=NULL)",
    }


@celery_app.task(name="tasks.check_lead_timeout")
def check_lead_timeout():
    """
    Beat job: find tickets in AI_FAILED routing state where no agent has
    self-claimed within the configured timeout window, and move them to the
    OPEN queue.
    """
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.LEAD_TIMEOUT_MINUTES)

    logger.info("check_lead_timeout: cutoff=%s", cutoff)

    async def _get_timed_out_ids() -> list[int]:
        async with AsyncSessionFactory() as session:
            repo = TicketRepository(session)
            tickets = await repo.get_lead_timed_out_tickets(cutoff)
            return [t.ticket_id for t in tickets]

    ticket_ids: list[int] = run_async(_get_timed_out_ids())

    moved: list[int] = []
    failed: list[int] = []

    for tid in ticket_ids:
        try:
            run_async(_move_to_open_queue(tid))
            moved.append(tid)
        except Exception:
            logger.exception("[ticket=%s] Failed to move to OPEN queue", tid)
            failed.append(tid)

    logger.info("check_lead_timeout: moved=%s failed=%s", moved, failed)
    return {"cutoff": cutoff.isoformat(), "moved_to_open_queue": moved, "failed": failed}