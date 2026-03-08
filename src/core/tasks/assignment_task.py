"""
src/core/tasks/assignment_task.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Auto-assignment Celery task.

Routing pipeline
----------------
1. Run AutoAssignmentService: score agents by experience / (1 + workload) for
   the ticket's area_of_concern, fall back to least-loaded agent globally.
2. If no agent found → fallback to least-loaded lead (via Auth Service).
3. If no lead available → move ticket to OPEN queue.
4. Beat job `check_lead_timeout` watches fallback-assigned tickets and moves them
   to the OPEN queue when the lead hasn't re-assigned within the configured window.
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

logger = logging.getLogger(__name__)



async def _score_assign_ticket(ticket_id: int) -> bool:
    """
    Delegate to AutoAssignmentService which scores agents using:
        score = experience / (1 + workload)

    Returns True  → an agent was assigned.
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
            logger.info(
                "[ticket=%s] Score-based routing SUCCESS → agent=%s "
                "(strategy=%s, score=%s)",
                ticket_id, result.assigned_to, result.strategy, result.score,
            )
            return True

        logger.info(
            "[ticket=%s] AutoAssignmentService found no agent (strategy=%s)",
            ticket_id, result.strategy,
        )
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Fallback: least-loaded lead  (original implementation)
# ─────────────────────────────────────────────────────────────────────────────

async def _fallback_to_lead(ticket_id: int) -> None:
    """
    Fallback when similarity routing fails.

    Strategy
    --------
    1. Fetch all users from Auth Service.
    2. Filter LEAD users.
    3. Select least-loaded lead by active ticket count.
    4. Assign ticket to that lead (routing_status = AI_FAILED so the
       beat job can watch it for the re-assign timeout).
    5. If no lead available → move ticket directly to OPEN queue.
    """
    now = datetime.now(timezone.utc)

    async with AsyncSessionFactory() as session:
        ticket_repo = TicketRepository(session)
        event_repo = TicketEventRepository(session)

        ticket = await ticket_repo.get_by_id(ticket_id, eager=False)

        if not ticket:
            logger.error("[ticket=%s] ticket not found", ticket_id)
            return

        if ticket.assignee_id:
            logger.info("[ticket=%s] already assigned", ticket_id)
            return

        lead_id: str | None = None

        try:
            users = await auth_client.get_all_users()

            if not users:
                raise Exception("No users returned from auth service")

            lead_ids = [
                u.lead_id for u in users if u.lead_id is not None
            ]

            if not lead_ids:
                raise Exception("No leads found")

            counts = await ticket_repo.get_ticket_count_for_leads(lead_ids)

            for lid in lead_ids:
                counts.setdefault(lid, 0)

            lead_id = min(counts, key=counts.get)

            logger.info(
                "[ticket=%s] least-loaded lead=%s ticket_count=%s",
                ticket_id,
                lead_id,
                counts[lead_id],
            )

        except Exception:
            logger.exception(
                "[ticket=%s] failed to resolve lead — moving to OPEN queue",
                ticket_id,
            )

        ticket.routing_status = RoutingStatus.AI_FAILED.value
        ticket.lead_assigned_at = now

        if lead_id:
            ticket.assignee_id = lead_id
            ticket.assigned_agent_id = None
            ticket.queue_type = QueueType.DIRECT.value

            await event_repo.add(
                TicketEvent(
                    ticket_id=ticket.ticket_id,
                    triggered_by_user_id=None,
                    event_type=EventType.ASSIGNED,
                    field_name="assignee_id",
                    old_value=None,
                    new_value=lead_id,
                    reason="AI routing failed — assigned to least loaded lead",
                )
            )

            logger.info(
                "[ticket=%s] assigned to lead=%s",
                ticket_id,
                lead_id,
            )

        else:
            ticket.assignee_id = None
            ticket.assigned_agent_id = None
            ticket.queue_type = QueueType.OPEN.value

            await event_repo.add(
                TicketEvent(
                    ticket_id=ticket.ticket_id,
                    triggered_by_user_id=None,
                    event_type=EventType.ASSIGNED,
                    field_name="assignee_id",
                    old_value=None,
                    new_value=QueueType.OPEN.value,
                    reason="AI routing failed and no lead available",
                )
            )

            logger.warning(
                "[ticket=%s] moved to OPEN queue",
                ticket_id,
            )

        await ticket_repo.save(ticket)
        await session.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — Beat timeout: move to OPEN queue if lead didn't re-assign
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

        old_assignee = ticket.assignee_id

        ticket.assignee_id = None
        ticket.assigned_agent_id = None
        ticket.queue_type = QueueType.OPEN.value
        ticket.status = TicketStatus.OPEN

        await ticket_repo.save(ticket)

        await event_repo.add(TicketEvent(
            ticket_id=ticket.ticket_id,
            triggered_by_user_id=None,
            event_type=EventType.STATUS_CHANGED,
            field_name="status",
            old_value=TicketStatus.ACKNOWLEDGED.value,
            new_value=TicketStatus.OPEN.value,
            reason=f"Fallback agent '{old_assignee}' did not re-assign within the timeout window",
        ))

        await session.commit()

        logger.info(
            "[ticket=%s] Moved to OPEN queue (fallback agent=%s timed out)",
            ticket_id, old_assignee,
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
    similarity_assign  →  SUCCESS  → done
         ↓ False / exception
    fallback_to_lead   →  lead assigned (AI_FAILED, beat job watches it)
                       →  no lead     → OPEN queue
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
        "message": "Score routing found no agent — assigned to least-loaded lead",
    }


@celery_app.task(name="tasks.check_lead_timeout")
def check_lead_timeout():
    """
    Beat job: find tickets where the fallback lead hasn't re-assigned within
    the configured timeout window and move them to the OPEN queue.
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