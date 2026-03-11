import logging
from datetime import datetime, timedelta, timezone

from src.celery_app import celery_app
from src.config.settings import get_settings
from src.constants.enum import EventType, TicketStatus
from src.core.services.notification.manager import notification_manager
from src.schemas.notification_schema import  AutoClosedRequest
from src.core.services.sla_service import SLAService
from src.core.services.ticket_service import TicketService
from src.data.clients.auth_client import auth_client
from src.data.clients.postgres_client import AsyncSessionFactory
from src.data.models.postgres.ticket_event import TicketEvent
from src.data.repositories.sla_repository import SLARepository
from src.data.repositories.sla_rule_repository import SLARuleRepository
from src.data.repositories.ticket_event_repository import TicketEventRepository
from src.data.repositories.ticket_repository import TicketRepository

from src.core.tasks._loop import run_async

logger = logging.getLogger(__name__)


def _make_sla_event(ticket, reason: str) -> TicketEvent:
    """
    Build a SLA_BREACHED TicketEvent for the timeline.
    Status does not change — old_value == new_value (same status).
    triggered_by_user_id = None signals a SYSTEM-triggered event.
    """
    return TicketEvent(
        ticket_id=ticket.ticket_id,
        triggered_by_user_id=None,
        event_type=EventType.SLA_BREACHED,
        field_name="sla",
        from_status=ticket.status.value,
        old_value=ticket.status.value,
        new_value=ticket.status.value,
        reason=reason,
    )


# ─────────────────────────────────────────────────────────────────────────────
# SLA breach detection
# ─────────────────────────────────────────────────────────────────────────────

@celery_app.task(name="tasks.detect_sla_breaches", bind=True, max_retries=3)
def detect_sla_breaches(self):
    try:
        run_async(_detect_sla_breaches_async())
    except Exception as exc:
        logger.exception("detect_sla_breaches failed: %s", exc)
        raise self.retry(exc=exc, countdown=30)


async def _detect_sla_breaches_async() -> None:
    now = datetime.now(timezone.utc)

    async with AsyncSessionFactory() as db:
        repo = TicketRepository(db)
        event_repo = TicketEventRepository(db)
        sla_svc = SLAService(SLARepository(db), SLARuleRepository(db))
        ticket_svc = TicketService(db, auth_client)

        # Pre-fetch all users once so we can resolve leads without N+1 calls
        all_users = []
        try:
            all_users = await auth_client.get_all_users()
            lead_users = [u for u in all_users if u.role in ("team_lead", "LEAD", "lead")]
            # Map: user_id → team_id  (for leads)
            lead_team_map: dict[str, str | None] = {u.id: u.team_id for u in lead_users}
            lead_ids: list[str] = list(lead_team_map.keys())
        except Exception:
            logger.exception("_detect_sla_breaches_async: failed to fetch users from auth service")
            lead_ids = []
            lead_team_map = {}

        def _resolve_lead(ticket) -> tuple[str | None, str | None]:
            """
            For a ticket, find the best lead to notify.

            Priority:
              1. The assignee's own lead_id (from auth data fetched above).
              2. Any lead that shares the ticket's team_id.
              3. First available lead.

            Returns (lead_id, lead_team_id).
            Never returns the current assignee as the lead.
            """
            if not lead_ids:
                return None, None

            # Try assignee's own lead_id
            if ticket.assignee_id:
                for u in all_users:
                    if u.id == ticket.assignee_id and u.lead_id and u.lead_id in lead_team_map:
                        return u.lead_id, lead_team_map[u.lead_id]

            # Prefer a lead from the same team
            if ticket.team_id:
                for lid in lead_ids:
                    if lead_team_map.get(lid) == ticket.team_id:
                        return lid, ticket.team_id

            # Any lead as last resort
            first = lead_ids[0]
            return first, lead_team_map.get(first)

        # ── Response SLA ──────────────────────────────────────────────
        response_candidates = await repo.get_response_sla_candidates(now)

        for ticket in response_candidates:
            if not sla_svc.check_response_breach(ticket, now):
                continue
            try:
                ticket.response_sla_breached_at = now
                ticket.escalation_level += 1
                ticket.is_breached = True
                ticket.is_escalated = True
                await repo.save(ticket)

                await event_repo.add(_make_sla_event(
                    ticket,
                    reason=f"Response SLA breached — escalation level {ticket.escalation_level}",
                ))

                lead_id, lead_team_id = _resolve_lead(ticket)

                await ticket_svc.escalate(
                    ticket=ticket,
                    reason=f"Response SLA breached — escalation level {ticket.escalation_level}",
                    now=now,
                    lead_id=lead_id,
                    lead_team_id=lead_team_id,
                )

                await db.commit()
                logger.info(
                    "response_sla_breached: ticket_id=%s level=%s lead=%s team=%s",
                    ticket.ticket_id, ticket.escalation_level, lead_id, lead_team_id,
                )
            except Exception as exc:
                await db.rollback()
                logger.error("response_breach failed ticket_id=%s: %s", ticket.ticket_id, exc)

        # ── Resolution SLA ────────────────────────────────────────────
        resolution_candidates = await repo.get_resolution_sla_candidates(now)

        for ticket in resolution_candidates:
            if not sla_svc.check_resolution_breach(ticket, now):
                continue
            try:
                ticket.resolution_sla_breached_at = now
                ticket.escalation_level += 1
                ticket.is_breached = True
                ticket.is_escalated = True
                await repo.save(ticket)

                await event_repo.add(_make_sla_event(
                    ticket,
                    reason=f"Resolution SLA breached — escalation level {ticket.escalation_level}",
                ))

                lead_id, lead_team_id = _resolve_lead(ticket)

                await ticket_svc.escalate(
                    ticket=ticket,
                    reason=f"Resolution SLA breached — escalation level {ticket.escalation_level}",
                    now=now,
                    lead_id=lead_id,
                    lead_team_id=lead_team_id,
                )

                await db.commit()
                logger.info(
                    "resolution_sla_breached: ticket_id=%s level=%s lead=%s team=%s",
                    ticket.ticket_id, ticket.escalation_level, lead_id, lead_team_id,
                )
            except Exception as exc:
                await db.rollback()
                logger.error("resolution_breach failed ticket_id=%s: %s", ticket.ticket_id, exc)


# ─────────────────────────────────────────────────────────────────────────────
# Auto-close resolved tickets
# ─────────────────────────────────────────────────────────────────────────────

@celery_app.task(name="tasks.auto_close_resolved_tickets", bind=True, max_retries=3)
def auto_close_resolved_tickets(self):
    try:
        run_async(_auto_close_async())
    except Exception as exc:
        logger.exception("auto_close_resolved_tickets failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)


async def _auto_close_async() -> None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=get_settings().AUTO_CLOSE_AFTER_HOURS)

    async with AsyncSessionFactory() as db:
        repo = TicketRepository(db)
        event_repo = TicketEventRepository(db)

        tickets = await repo.get_auto_closeable(cutoff)
        if not tickets:
            logger.debug("auto_close: no candidates at %s", now)
            return

        for ticket in tickets:
            try:
                old_status = ticket.status
                ticket.status = TicketStatus.CLOSED
                ticket.auto_closed = True
                await repo.save(ticket)

                await event_repo.add(TicketEvent(
                    ticket_id=ticket.ticket_id,
                    triggered_by_user_id=None,
                    event_type=EventType.STATUS_CHANGED,
                    field_name="status",
                    from_status=old_status.value,
                    old_value=old_status.value,
                    new_value=TicketStatus.CLOSED.value,
                    reason="Auto-closed after 72h in RESOLVED",
                ))

                await notification_manager.send(
                    request=AutoClosedRequest(
                        ticket_id=ticket.ticket_id,
                        ticket_number=ticket.ticket_number,
                        ticket_title=ticket.title,
                        customer_id=ticket.customer_id,
                    ),
                    db=db,
                    auth_client=auth_client,
                )

                await db.commit()
                logger.info(
                    "auto_closed: ticket_id=%s number=%s",
                    ticket.ticket_id, ticket.ticket_number,
                )
            except Exception as exc:
                await db.rollback()
                logger.error("auto_close failed ticket_id=%s: %s", ticket.ticket_id, exc)