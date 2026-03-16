from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import func, select, or_
from src.constants.enum import QueueType, RoutingStatus, TicketStatus
from src.data.models.postgres.ticket import Ticket
from src.schemas.ticket_schema import TicketListFilters


_EAGER = [
    selectinload(Ticket.attachments),
    selectinload(Ticket.comments),
    selectinload(Ticket.events),
]


class TicketRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── READ ─────────────────────────────────────────────────────────────────

    async def get_by_id(self, ticket_id: int, eager: bool = True) -> Optional[Ticket]:
        stmt = select(Ticket).where(Ticket.ticket_id == ticket_id)
        if eager:
            stmt = stmt.options(*_EAGER)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_number(self, ticket_number: str) -> Optional[Ticket]:
        result = await self.db.execute(
            select(Ticket)
            .where(Ticket.ticket_number == ticket_number)
            .options(*_EAGER)
        )
        return result.scalar_one_or_none()

    async def next_ticket_number(self) -> str:
       
        result = await self.db.execute(select(func.count(Ticket.ticket_id)))
        count = result.scalar_one()
        return f"TKT-{count + 1:04d}"

    async def list_for_customer(
        self, customer_id: str, filters: TicketListFilters
    ) -> tuple[int, list[Ticket]]:
        stmt = select(Ticket).where(Ticket.customer_id == customer_id)
        stmt = self._apply_filters(stmt, filters)
        return await self._paginate(stmt, filters)

    async def list_all(
        self, filters: TicketListFilters
    ) -> tuple[int, list[Ticket]]:
        stmt = select(Ticket).options(*_EAGER)
        stmt = self._apply_filters(stmt, filters)
        return await self._paginate(stmt, filters)

    async def get_breachable(self, now: datetime) -> list[Ticket]:
        result = await self.db.execute(
            select(Ticket).where(
                Ticket.resolution_due_at < now,
                Ticket.status.not_in([TicketStatus.RESOLVED, TicketStatus.CLOSED]),
                Ticket.is_breached == False,  # noqa: E712
            )
        )
        return list(result.scalars().all())

    async def get_escalatable(self, now: datetime) -> list[Ticket]:
        result = await self.db.execute(
            select(Ticket).where(
                or_(
    Ticket.resolution_sla_breached_at.isnot(None),
    Ticket.response_sla_breached_at.isnot(None)
),
                Ticket.escalation_level > 0, # noqa: E712
                Ticket.status.not_in([TicketStatus.RESOLVED, TicketStatus.CLOSED]),
            )
        )
        return list(result.scalars().all())

    async def get_resolved_by_assignees(
        self, assignee_ids: list[str],
    ) -> list[Ticket]:
        """
        Return tickets in RESOLVED or CLOSED status for the given assignee IDs.
        Used by the assignment agent to understand each agent's historical expertise.
        """
        if not assignee_ids:
            return []
        result = await self.db.execute(
            select(Ticket)
            .where(
                Ticket.assignee_id.in_(assignee_ids),
                Ticket.status.in_([TicketStatus.RESOLVED, TicketStatus.CLOSED]),
            )
            .order_by(Ticket.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_active_ticket_counts_for_agents(
        self, agent_ids: list[str]
    ) -> dict[str, int]:
        """
        Return ``{agent_id: active_ticket_count}`` for each ID in *agent_ids*.

        "Active" means any status that is NOT RESOLVED or CLOSED.  Agents
        that have zero active tickets are still included in the result with
        a count of 0, making it safe to use the dict as an availability
        proxy without a separate join.
        """
        if not agent_ids:
            return {}
        result = await self.db.execute(
            select(Ticket.assignee_id, func.count(Ticket.ticket_id).label("cnt"))
            .where(
                Ticket.assignee_id.in_(agent_ids),
                Ticket.status.not_in([TicketStatus.RESOLVED, TicketStatus.CLOSED]),
            )
            .group_by(Ticket.assignee_id)
        )
        counts = {row.assignee_id: row.cnt for row in result.fetchall()}
        # Agents not in the result set have no active tickets at all
        return {aid: counts.get(aid, 0) for aid in agent_ids}

    async def get_least_loaded_experienced_agent(
        self,
        max_active_tickets: int = 10,
        exclude_ids: set[str] | None = None,
    ) -> str | None:

        # Step 1 – experienced agents (at least one resolved/closed ticket)
        exp_stmt = (
            select(Ticket.assignee_id)
            .where(
                Ticket.assignee_id.isnot(None),
                Ticket.status.in_([TicketStatus.RESOLVED, TicketStatus.CLOSED]),
            )
            .distinct()
        )
        if exclude_ids:
            exp_stmt = exp_stmt.where(Ticket.assignee_id.not_in(exclude_ids))

        exp_result = await self.db.execute(exp_stmt)
        experienced: set[str] = {row[0] for row in exp_result.fetchall()}

        if not experienced:
            return None

        # Step 2 – active ticket counts for that pool
        active_result = await self.db.execute(
            select(Ticket.assignee_id, func.count(Ticket.ticket_id).label("active_cnt"))
            .where(
                Ticket.assignee_id.in_(list(experienced)),
                Ticket.status.not_in([TicketStatus.RESOLVED, TicketStatus.CLOSED]),
            )
            .group_by(Ticket.assignee_id)
        )
        active_counts: dict[str, int] = {
            row.assignee_id: row.active_cnt for row in active_result.fetchall()
        }

        def _load(agent_id: str) -> int:
            return active_counts.get(agent_id, 0)

        # Step 3 – prefer agents under the cap
        under_cap = [aid for aid in experienced if _load(aid) < max_active_tickets]
        if under_cap:
            return min(under_cap, key=_load)

        # Step 4 – all over cap: pick the least-loaded anyway
        return min(experienced, key=_load)

    async def get_last_assigned_agent(
        self,
        exclude_ticket_id: int | None = None,
        exclude_agent_id: str | None = None,
    ) -> str | None:
        """
        Return the ``assignee_id`` of the most recently assigned ticket.

        Parameters
        ----------
        exclude_ticket_id:
            The ticket currently being routed — skip it so we don't assign
            a ticket to itself.
        exclude_agent_id:
            Skip a specific agent (e.g. one already tried and found
            unsuitable).
        """
        stmt = (
            select(Ticket.assignee_id)
            .where(Ticket.assignee_id.isnot(None))
            .order_by(Ticket.created_at.desc())
            .limit(1)
        )
        if exclude_ticket_id is not None:
            stmt = stmt.where(Ticket.ticket_id != exclude_ticket_id)
        if exclude_agent_id is not None:
            stmt = stmt.where(Ticket.assignee_id != exclude_agent_id)

        result = await self.db.execute(stmt)
        row = result.fetchone()
        return row[0] if row else None

    async def get_least_loaded_lead(
        self,
        exclude_agent_id: str | None = None,
    ) -> str | None:
        
        # Step 1 — infer leads from AI_FAILED routing history
        leads_stmt = (
            select(Ticket.assignee_id)
            .where(
                Ticket.assignee_id.isnot(None),
                Ticket.routing_status == RoutingStatus.AI_FAILED.value,
            )
            .distinct()
        )
        if exclude_agent_id is not None:
            leads_stmt = leads_stmt.where(Ticket.assignee_id != exclude_agent_id)

        leads_result = await self.db.execute(leads_stmt)
        lead_ids: set[str] = {row[0] for row in leads_result.fetchall()}

        if not lead_ids:
            return None

        # Step 2 — count active tickets per lead
        active_result = await self.db.execute(
            select(Ticket.assignee_id, func.count(Ticket.ticket_id).label("active_cnt"))
            .where(
                Ticket.assignee_id.in_(list(lead_ids)),
                Ticket.status.not_in([TicketStatus.RESOLVED, TicketStatus.CLOSED]),
            )
            .group_by(Ticket.assignee_id)
        )
        active_counts: dict[str, int] = {
            row.assignee_id: row.active_cnt for row in active_result.fetchall()
        }

        # Step 3 — pick the lead with the smallest active load
        return min(lead_ids, key=lambda aid: active_counts.get(aid, 0))

    async def get_lead_timed_out_tickets(self, cutoff: datetime) -> list[Ticket]:
        """
        Return tickets that were routed to a lead's team queue (AI_FAILED +
        DIRECT) but no agent has self-claimed them within the timeout window.

        Key invariant: fallback tickets have assignee_id = NULL intentionally
        (agents self-claim). The old code wrongly filtered assignee_id IS NOT NULL
        which meant this query always returned zero rows and the timeout path
        was silently broken.

        Also fixed: the original code had fallback_assigned_at == None AND
        fallback_assigned_at < cutoff which is a logical contradiction — both
        conditions can never be true simultaneously. Correct filter is IS NOT NULL
        + < cutoff.
        """
        result = await self.db.execute(
            select(Ticket).where(
                Ticket.routing_status == RoutingStatus.AI_FAILED.value,
                Ticket.queue_type == QueueType.DIRECT.value,
                Ticket.fallback_assigned_at.isnot(None),   # must have been through fallback
                Ticket.fallback_assigned_at < cutoff,       # and timed out
                Ticket.assignee_id.is_(None),               # not yet self-claimed by an agent
                Ticket.status.in_([
                    TicketStatus.ACKNOWLEDGED,
                    TicketStatus.OPEN,
                    TicketStatus.NEW,
                ]),
            )
        )
        return list(result.scalars().all())

    async def get_response_sla_candidates(self, now: datetime) -> list[Ticket]:
        """
        Tickets whose response SLA *may* be breached right now.
        The actual breach check is done by SLAService.check_response_breach().
        """
        result = await self.db.execute(
            select(Ticket).where(
                Ticket.response_sla_started_at.isnot(None),
                Ticket.response_sla_deadline_minutes.isnot(None),
                Ticket.response_sla_completed_at.is_(None),
                Ticket.response_sla_breached_at.is_(None),
                Ticket.status.in_([
                    TicketStatus.NEW,
                    TicketStatus.ACKNOWLEDGED,
                    TicketStatus.OPEN,
                ]),
            )
        )
        return list(result.scalars().all())

    async def get_resolution_sla_candidates(self, now: datetime) -> list[Ticket]:
        """
        Tickets whose resolution SLA *may* be breached right now.
        The actual breach check is done by SLAService.check_resolution_breach().
        """
        result = await self.db.execute(
            select(Ticket).where(
                Ticket.resolution_sla_started_at.isnot(None),
                Ticket.resolution_sla_deadline_minutes.isnot(None),
                Ticket.resolution_sla_completed_at.is_(None),
                Ticket.resolution_sla_breached_at.is_(None),
                Ticket.resolution_sla_paused_at.is_(None),
                Ticket.status == TicketStatus.IN_PROGRESS,
            )
        )
        return list(result.scalars().all())

    async def get_auto_closeable(self, cutoff: datetime) -> list[Ticket]:
        """
        Tickets in RESOLVED status whose resolution was completed before *cutoff*
        and have not yet been auto-closed.
        """
        result = await self.db.execute(
            select(Ticket).where(
                Ticket.status == TicketStatus.RESOLVED,
                Ticket.auto_closed == False,  # noqa: E712
                Ticket.resolution_sla_completed_at.isnot(None),
                Ticket.resolution_sla_completed_at <= cutoff,
            )
        )
        return list(result.scalars().all())

    # ── WRITE ────────────────────────────────────────────────────────────────

    async def create(self, ticket: Ticket) -> Ticket:
        """Persist a new ticket and return it with all relations loaded."""
        self.db.add(ticket)
        await self.db.flush()
        # Re-fetch with eager relations so Pydantic can serialise immediately
        return await self.get_by_id(ticket.ticket_id, eager=True)

    async def save(self, ticket: Ticket) -> Ticket:
        """Update an existing ticket and return it with relations loaded."""
        self.db.add(ticket)
        await self.db.flush()
        return await self.get_by_id(ticket.ticket_id, eager=True)

    # ── INTERNAL ─────────────────────────────────────────────────────────────

    def _apply_filters(self, stmt, filters: TicketListFilters):
        if filters.status:
            stmt = stmt.where(Ticket.status == filters.status)
        if filters.severity:
            stmt = stmt.where(Ticket.severity == filters.severity)
        if filters.priority:
            stmt = stmt.where(Ticket.priority == filters.priority)
        if filters.customer_id:
            stmt = stmt.where(Ticket.customer_id == filters.customer_id)
        if filters.assignee_id:
            stmt = stmt.where(Ticket.assignee_id == filters.assignee_id)
        if filters.assignee_ids:
            stmt = stmt.where(Ticket.assignee_id.in_(filters.assignee_ids))
        if filters.is_breached is not None:
            if filters.is_breached:
                stmt = stmt.where(
                    (Ticket.resolution_sla_breached_at.isnot(None)) | 
                    (Ticket.response_sla_breached_at.isnot(None))
                )
            else:
                stmt = stmt.where(
                    Ticket.resolution_sla_breached_at.is_(None),
                    Ticket.response_sla_breached_at.is_(None)
                )
        if filters.is_escalated is not None:
            stmt = stmt.where(Ticket.is_escalated == filters.is_escalated)
        if filters.is_unassigned is not None:
            if filters.is_unassigned:
                stmt = stmt.where(
                    Ticket.assignee_id.is_(None),
                    Ticket.status.not_in([TicketStatus.RESOLVED, TicketStatus.CLOSED]),
                )
            else:
                stmt = stmt.where(Ticket.assignee_id.isnot(None))
        if filters.team_id:
            stmt = stmt.where(Ticket.team_id == filters.team_id)
        if filters.queue_type:
            # Note: QueueType.OPEN represents the unassigned Open Queue
            if filters.queue_type == QueueType.OPEN.value:
                stmt = stmt.where(
                    Ticket.queue_type == QueueType.OPEN.value,
                    Ticket.assignee_id.is_(None),
                    Ticket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS]),
                    Ticket.routing_status == RoutingStatus.AI_FAILED.value,
                    Ticket.escalation_level == 0
                )
            else:
                stmt = stmt.where(Ticket.queue_type == filters.queue_type)
        if filters.routing_status:
            stmt = stmt.where(Ticket.routing_status == filters.routing_status)
        return stmt

    async def _paginate(
        self, stmt, filters: TicketListFilters
    ) -> tuple[int, list[Ticket]]:
        count_result = await self.db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total = count_result.scalar_one()

        stmt = stmt.order_by(Ticket.created_at.desc())
        stmt = stmt.offset((filters.page - 1) * filters.page_size).limit(filters.page_size)

        result = await self.db.execute(stmt)
        return total, list(result.scalars().all())
    
    async def get_ticket_count_for_leads(self, lead_ids: list[str]) -> dict[str, int]:
        stmt = (
            select(Ticket.assignee_id, func.count(Ticket.ticket_id))
            .where(Ticket.assignee_id.in_(lead_ids))
            .where(Ticket.status.not_in([TicketStatus.CLOSED, TicketStatus.ACKNOWLEDGED, TicketStatus.NEW]))
            .group_by(Ticket.assignee_id)
        )

        result = await self.db.execute(stmt)
        
        counts = {lead_id: count for lead_id, count in result.all()}

        for lead_id in lead_ids:
            counts.setdefault(lead_id, 0)

        return counts