"""Pydantic v2 schemas for Analytics / Reporting endpoints."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Ticket distribution breakdowns ───────────────────────────────────────────
class CountByField(BaseModel):
    """Generic label → count bucket."""
    label: str
    count: int


class TicketSummary(BaseModel):
    total_tickets: int = 0
    open_tickets: int = 0
    in_progress_tickets: int = 0
    on_hold_tickets: int = 0
    resolved_tickets: int = 0
    closed_tickets: int = 0
    breached_tickets: int = 0
    escalated_tickets: int = 0


class TicketDistribution(BaseModel):
    by_status: list[CountByField] = Field(default_factory=list)
    by_severity: list[CountByField] = Field(default_factory=list)
    by_priority: list[CountByField] = Field(default_factory=list)
    by_product: list[CountByField] = Field(default_factory=list)


# ── Agent performance ────────────────────────────────────────────────────────
class AgentPerformance(BaseModel):
    agent_user_id: str
    display_name: str
    total_assigned: int = 0
    total_resolved: int = 0
    total_breached: int = 0
    avg_resolution_minutes: Optional[float] = None


# ── SLA compliance ────────────────────────────────────────────────────────────
class SLAComplianceReport(BaseModel):
    total_tickets: int = 0
    response_sla_met: int = 0
    response_sla_breached: int = 0
    resolution_sla_met: int = 0
    resolution_sla_breached: int = 0
    response_compliance_pct: float = 0.0
    resolution_compliance_pct: float = 0.0


# ── Customer report ───────────────────────────────────────────────────────────
class CustomerTicketReport(BaseModel):
    customer_id: str
    total_tickets: int = 0
    open_tickets: int = 0
    resolved_tickets: int = 0
    breached_tickets: int = 0


# ── Team comparison (ADMIN only) ─────────────────────────────────────────
class TeamComparison(BaseModel):
    """Per-team aggregate used in cross-team comparison (ADMIN only)."""
    team_name: str
    total_tickets: int = 0
    resolved_tickets: int = 0
    breached_tickets: int = 0


# ── Combined dashboard ───────────────────────────────────────────────────────
class AdminDashboard(BaseModel):
    data_scope: str = Field(
        default="GLOBAL",
        description="Data visibility scope: GLOBAL (admin) or TEAM (lead).",
    )
    summary: TicketSummary
    distribution: TicketDistribution
    sla_compliance: SLAComplianceReport
    top_agents: list[AgentPerformance] = Field(default_factory=list)
    team_comparison: list[TeamComparison] = Field(default_factory=list)


# ── Filters ───────────────────────────────────────────────────────────────────
class AnalyticsFilters(BaseModel):
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    product: Optional[str] = None
    customer_tier_id: Optional[int] = None
