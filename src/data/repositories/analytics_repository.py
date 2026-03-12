"""
Analytics repository — read-only queries against the ``tickets`` table for reporting.

This repository must NOT mutate any table.
It performs aggregate / GROUP BY queries on the tickets table only.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enum import TicketStatus
from src.data.models.postgres.ticket import Ticket


class AnalyticsRepository:
    """Read-only aggregate queries on the ``tickets`` table for dashboards."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── helpers ───────────────────────────────────────────────────────────────

    def _apply_date_filters(
        self,
        stmt,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        product: Optional[str] = None,
        customer_tier_id: Optional[int] = None,
        assignee_ids: Optional[list] = None,
    ):
        if date_from:
            stmt = stmt.where(Ticket.created_at >= date_from)
        if date_to:
            stmt = stmt.where(Ticket.created_at <= date_to)
        if product:
            stmt = stmt.where(Ticket.product == product)
        if customer_tier_id:
            stmt = stmt.where(Ticket.customer_tier_id == customer_tier_id)
        if assignee_ids:
            stmt = stmt.where(Ticket.assignee_id.in_(assignee_ids))
        return stmt

    # ── summary counts ────────────────────────────────────────────────────────

    async def get_ticket_summary(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        product: Optional[str] = None,
        customer_tier_id: Optional[int] = None,
        assignee_ids: Optional[list] = None,
    ) -> dict:
        base = select(
            func.count(Ticket.ticket_id).label("total"),
            func.count(case((Ticket.status == TicketStatus.OPEN, 1))).label("open"),
            func.count(case((Ticket.status == TicketStatus.IN_PROGRESS, 1))).label("in_progress"),
            func.count(case((Ticket.status == TicketStatus.ON_HOLD, 1))).label("on_hold"),
            func.count(case((Ticket.status == TicketStatus.RESOLVED, 1))).label("resolved"),
            func.count(case((Ticket.status == TicketStatus.CLOSED, 1))).label("closed"),
            func.count(case((Ticket.response_sla_breached_at.isnot(None), 1))).label("breached"),
            func.count(case((Ticket.escalation_level > 0, 1))).label("escalated"),
        )
        base = self._apply_date_filters(base, date_from, date_to, product, customer_tier_id, assignee_ids)
        row = (await self.db.execute(base)).one()
        return {
            "total_tickets": row.total,
            "open_tickets": row.open,
            "in_progress_tickets": row.in_progress,
            "on_hold_tickets": row.on_hold,
            "resolved_tickets": row.resolved,
            "closed_tickets": row.closed,
            "breached_tickets": row.breached,
            "escalated_tickets": row.escalated,
        }

    # ── distribution ──────────────────────────────────────────────────────────

    async def _count_by(
        self,
        column,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        product: Optional[str] = None,
        customer_tier_id: Optional[int] = None,
        assignee_ids: Optional[list] = None,
    ) -> list[dict]:
        stmt = select(column, func.count(Ticket.ticket_id).label("cnt")).group_by(column)
        stmt = self._apply_date_filters(stmt, date_from, date_to, product, customer_tier_id, assignee_ids)
        rows = (await self.db.execute(stmt)).all()
        return [{"label": str(r[0].value if hasattr(r[0], "value") else r[0]), "count": r.cnt} for r in rows]

    async def get_distribution(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        product: Optional[str] = None,
        customer_tier_id: Optional[int] = None,
        assignee_ids: Optional[list] = None,
    ) -> dict:
        kw = dict(date_from=date_from, date_to=date_to, product=product, customer_tier_id=customer_tier_id, assignee_ids=assignee_ids)
        return {
            "by_status": await self._count_by(Ticket.status, **kw),
            "by_severity": await self._count_by(Ticket.severity, **kw),
            "by_priority": await self._count_by(Ticket.priority, **kw),
            "by_product": await self._count_by(Ticket.product, **kw),
        }

    # ── agent performance ─────────────────────────────────────────────────────

    async def get_agent_stats(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        assignee_ids: Optional[list] = None,
    ) -> list[dict]:
        """Per-assignee aggregates: total assigned, resolved, breached, avg resolution."""
        stmt = (
            select(
                Ticket.assignee_id,
                func.count(Ticket.ticket_id).label("total_assigned"),
                func.count(case((
                    Ticket.status.in_([TicketStatus.RESOLVED, TicketStatus.CLOSED]), 1
                ))).label("total_resolved"),
                func.count(case((
                    Ticket.response_sla_breached_at.isnot(None), 1
                ))).label("total_breached"),
                func.avg(
                    case((
                        Ticket.resolution_sla_completed_at.isnot(None),
                        func.extract(
                            "epoch",
                            Ticket.resolution_sla_completed_at - Ticket.resolution_sla_started_at,
                        ) / 60,
                    ))
                ).label("avg_resolution_minutes"),
            )
            .where(Ticket.assignee_id.isnot(None))
            .group_by(Ticket.assignee_id)
        )
        if assignee_ids:
            stmt = stmt.where(Ticket.assignee_id.in_(assignee_ids))
        if date_from:
            stmt = stmt.where(Ticket.created_at >= date_from)
        if date_to:
            stmt = stmt.where(Ticket.created_at <= date_to)
        rows = (await self.db.execute(stmt)).all()
        return [
            {
                "agent_user_id": r.assignee_id,
                "total_assigned": r.total_assigned,
                "total_resolved": r.total_resolved,
                "total_breached": r.total_breached,
                "avg_resolution_minutes": round(r.avg_resolution_minutes, 2) if r.avg_resolution_minutes else None,
            }
            for r in rows
        ]

    # ── SLA compliance ────────────────────────────────────────────────────────

    async def get_sla_compliance(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        product: Optional[str] = None,
        customer_tier_id: Optional[int] = None,
        assignee_ids: Optional[list] = None,
    ) -> dict:
        stmt = select(
            func.count(Ticket.ticket_id).label("total"),
            # response SLA
            func.count(case((
                Ticket.response_sla_completed_at.isnot(None)
                & Ticket.response_sla_breached_at.is_(None), 1
            ))).label("resp_met"),
            func.count(case((Ticket.response_sla_breached_at.isnot(None), 1))).label("resp_breached"),
            # resolution SLA
            func.count(case((
                Ticket.resolution_sla_completed_at.isnot(None)
                & Ticket.resolution_sla_breached_at.is_(None), 1
            ))).label("res_met"),
            func.count(case((Ticket.resolution_sla_breached_at.isnot(None), 1))).label("res_breached"),
        )
        stmt = self._apply_date_filters(stmt, date_from, date_to, product, customer_tier_id)
        row = (await self.db.execute(stmt)).one()
        total = row.total or 1  # avoid division by zero
        return {
            "total_tickets": row.total,
            "response_sla_met": row.resp_met,
            "response_sla_breached": row.resp_breached,
            "resolution_sla_met": row.res_met,
            "resolution_sla_breached": row.res_breached,
            "response_compliance_pct": round(row.resp_met / total * 100, 2),
            "resolution_compliance_pct": round(row.res_met / total * 100, 2),
        }

    # ── customer report ───────────────────────────────────────────────────────

    async def get_customer_reports(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> list[dict]:
        stmt = (
            select(
                Ticket.customer_id,
                func.count(Ticket.ticket_id).label("total"),
                func.count(case((
                    Ticket.status.in_([
                        TicketStatus.NEW, TicketStatus.ACKNOWLEDGED,
                        TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.ON_HOLD,
                    ]), 1
                ))).label("open_tickets"),
                func.count(case((
                    Ticket.status.in_([TicketStatus.RESOLVED, TicketStatus.CLOSED]), 1
                ))).label("resolved"),
                func.count(case((
                    Ticket.response_sla_breached_at.isnot(None), 1
                ))).label("breached"),
            )
            .group_by(Ticket.customer_id)
        )
        if date_from:
            stmt = stmt.where(Ticket.created_at >= date_from)
        if date_to:
            stmt = stmt.where(Ticket.created_at <= date_to)
        rows = (await self.db.execute(stmt)).all()
        return [
            {
                "customer_id": r.customer_id,
                "total_tickets": r.total,
                "open_tickets": r.open_tickets,
                "resolved_tickets": r.resolved,
                "breached_tickets": r.breached,
            }
            for r in rows
        ]

    # ── per-customer summary (for CUSTOMER role) ──────────────────────────────

    async def get_my_summary(self, customer_id: str) -> dict:
        stmt = select(
            func.count(Ticket.ticket_id).label("total"),
            func.count(case((
                Ticket.status.in_([
                    TicketStatus.NEW, TicketStatus.ACKNOWLEDGED,
                    TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.ON_HOLD,
                ]), 1
            ))).label("open_tickets"),
            func.count(case((
                Ticket.status.in_([TicketStatus.RESOLVED, TicketStatus.CLOSED]), 1
            ))).label("resolved"),
            func.count(case((Ticket.response_sla_breached_at.isnot(None), 1))).label("breached"),
        ).where(Ticket.customer_id == customer_id)
        row = (await self.db.execute(stmt)).one()
        return {
            "customer_id": customer_id,
            "total_tickets": row.total,
            "open_tickets": row.open_tickets,
            "resolved_tickets": row.resolved,
            "breached_tickets": row.breached,
        }

    # ── per-agent summary (for AGENT role) ────────────────────────────────────

    async def get_agent_summary(self, agent_user_id: str) -> dict:
        stmt = select(
            func.count(Ticket.ticket_id).label("total_assigned"),
            func.count(case((
                Ticket.status.in_([TicketStatus.RESOLVED, TicketStatus.CLOSED]), 1
            ))).label("total_resolved"),
            func.count(case((Ticket.response_sla_breached_at.isnot(None), 1))).label("total_breached"),
            func.avg(
                case((
                    Ticket.resolution_sla_completed_at.isnot(None),
                    func.extract(
                        "epoch",
                        Ticket.resolution_sla_completed_at - Ticket.resolution_sla_started_at,
                    ) / 60,
                ))
            ).label("avg_resolution_minutes"),
        ).where(Ticket.assignee_id == agent_user_id)
        row = (await self.db.execute(stmt)).one()
        return {
            "agent_user_id": agent_user_id,
            "total_assigned": row.total_assigned,
            "total_resolved": row.total_resolved,
            "total_breached": row.total_breached,
            "avg_resolution_minutes": round(row.avg_resolution_minutes, 2) if row.avg_resolution_minutes else None,
        }