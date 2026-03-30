"""Service for Analytics / Reporting — role-based dashboards."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enum import UserRole
from src.core.exceptions.base import InsufficientPermissionsError
from src.data.repositories.analytics_repository import AnalyticsRepository
from src.data.clients.auth_client import AuthServiceClient
from typing import Optional
from src.schemas.analytics_schema import (
    AdminDashboard,
    AgentPerformance,
    AnalyticsFilters,
    CustomerTicketReport,
    SLAComplianceReport,
    TeamComparison,
    TicketDistribution,
    TicketSummary,
)

logger = logging.getLogger(__name__)


class AnalyticsService:
    def __init__(self, db: AsyncSession) -> None:
        """
          init  .
        
        Args:
            db (AsyncSession): Input parameter.
        """
        self.db = db
        self._analytics_repo = AnalyticsRepository(db)

    # ── Admin / Lead dashboard ────────────────────────────────────────────────

    async def get_admin_dashboard(
        self,
        filters: AnalyticsFilters,
        current_user_role: str,
        assignee_ids: Optional[list[str]] = None,
        auth_client: Optional[AuthServiceClient] = None,
    ) -> AdminDashboard:
        """
        Get admin dashboard.
        
        Args:
            filters (AnalyticsFilters): Input parameter.
            current_user_role (str): Input parameter.
            assignee_ids (Optional[list[str]]): Input parameter.
            auth_client (Optional[AuthServiceClient]): Input parameter.
        
        Returns:
            AdminDashboard: The expected output.
        """
        role = UserRole(current_user_role)
        if role not in (UserRole.LEAD, UserRole.ADMIN):
            raise InsufficientPermissionsError("Only team leads and admins can view the dashboard.")

        kw = dict(
            date_from=filters.date_from,
            date_to=filters.date_to,
            product=filters.product,
            customer_tier_id=filters.customer_tier_id,
            assignee_ids=assignee_ids,
        )

        summary_data = await self._analytics_repo.get_ticket_summary(**kw)
        dist_data = await self._analytics_repo.get_distribution(**kw)
        sla_data = await self._analytics_repo.get_sla_compliance(**kw)
        agent_rows = await self._analytics_repo.get_agent_stats(
            date_from=filters.date_from, date_to=filters.date_to,
            assignee_ids=assignee_ids,
        )

        # Enrich agent rows with display_name from Auth Service
        top_agents: list[AgentPerformance] = []
        for row in agent_rows:
            agent_user_id = row["agent_user_id"]

            if auth_client:
                try:
                    user = await auth_client.get_user(agent_user_id)
                    display_name = user.full_name or user.email.split("@")[0]
                except Exception:
                    display_name = agent_user_id[:8] + "…"
            else:
                display_name = agent_user_id[:8] + "…"

            top_agents.append(AgentPerformance(
                agent_user_id=agent_user_id,
                display_name=display_name,
                total_assigned=row["total_assigned"],
                total_resolved=row["total_resolved"],
                total_breached=row["total_breached"],
                avg_resolution_minutes=row["avg_resolution_minutes"],
            ))

        # ── Determine data scope ──────────────────────────────────────────
        role = UserRole(current_user_role)
        data_scope = "GLOBAL" if role == UserRole.ADMIN else "TEAM"

        # ── ADMIN-only: cross-team comparison ─────────────────────────────
        team_comparison: list[TeamComparison] = []
        if role == UserRole.ADMIN and auth_client:
            try:
                raw_rows = await self._analytics_repo.get_team_comparison(
                    date_from=filters.date_from,
                    date_to=filters.date_to,
                )
                all_users = await auth_client.get_all_users()
                # Build assignee_id → lead_id → team_name mapping
                lead_map: dict[str, str] = {}
                lead_names: dict[str, str] = {}
                for u in all_users:
                    if u.lead_id:
                        lead_map[u.id] = u.lead_id
                    if u.role == "team_lead":
                        lead_names[u.id] = u.full_name or u.email.split("@")[0]

                # Bucket per-assignee rows into per-team aggregates
                team_buckets: dict[str, dict] = {}
                for row in raw_rows:
                    aid = row["assignee_id"]
                    lead_id = lead_map.get(aid, "unassigned")
                    tname = lead_names.get(lead_id, f"Team {lead_id[:6]}…")
                    if tname not in team_buckets:
                        team_buckets[tname] = {"total": 0, "resolved": 0, "breached": 0}
                    team_buckets[tname]["total"] += row["total"]
                    team_buckets[tname]["resolved"] += row["resolved"]
                    team_buckets[tname]["breached"] += row["breached"]

                team_comparison = [
                    TeamComparison(
                        team_name=name,
                        total_tickets=vals["total"],
                        resolved_tickets=vals["resolved"],
                        breached_tickets=vals["breached"],
                    )
                    for name, vals in team_buckets.items()
                ]
            except Exception:
                logger.warning("Failed to build team comparison data", exc_info=True)

        return AdminDashboard(
            data_scope=data_scope,
            summary=TicketSummary(**summary_data),
            distribution=TicketDistribution(**dist_data),
            sla_compliance=SLAComplianceReport(**sla_data),
            top_agents=top_agents,
            team_comparison=team_comparison,
        )

    # ── SLA Compliance report ─────────────────────────────────────────────────

    async def get_sla_compliance(
        self,
        filters: AnalyticsFilters,
        current_user_role: str,
        assignee_ids: Optional[list[str]] = None,
    ) -> SLAComplianceReport:
        """
        Get sla compliance.
        
        Args:
            filters (AnalyticsFilters): Input parameter.
            current_user_role (str): Input parameter.
            assignee_ids (Optional[list[str]]): Input parameter.
        
        Returns:
            SLAComplianceReport: The expected output.
        """
        role = UserRole(current_user_role)
        if role not in (UserRole.LEAD, UserRole.ADMIN):
            raise InsufficientPermissionsError("Only team leads and admins can view SLA compliance.")

        data = await self._analytics_repo.get_sla_compliance(
            date_from=filters.date_from,
            date_to=filters.date_to,
            product=filters.product,
            customer_tier_id=filters.customer_tier_id,
            assignee_ids=assignee_ids,
        )
        return SLAComplianceReport(**data)

    # ── Agent performance (for LEAD/ADMIN or self) ────────────────────────────

    async def get_agent_performance(
        self,
        agent_user_id: str,
        current_user_id: str,
        current_user_role: str,
        auth_client: Optional[AuthServiceClient] = None,
    ) -> AgentPerformance:
        """
        Get agent performance.
        
        Args:
            agent_user_id (str): Input parameter.
            current_user_id (str): Input parameter.
            current_user_role (str): Input parameter.
            auth_client (Optional[AuthServiceClient]): Input parameter.
        
        Returns:
            AgentPerformance: The expected output.
        """
        role = UserRole(current_user_role)
        if role == UserRole.AGENT and agent_user_id != current_user_id:
            raise InsufficientPermissionsError("Agents can only view their own performance.")
        if role == UserRole.CUSTOMER:
            raise InsufficientPermissionsError("Customers cannot view agent performance.")

        data = await self._analytics_repo.get_agent_summary(agent_user_id)

        # Resolve display_name from Auth Service
        display_name = "Unknown"
        if auth_client:
            try:
                user = await auth_client.get_user(agent_user_id)
                display_name = user.full_name or user.email.split("@")[0]
            except Exception:
                display_name = agent_user_id[:8] + "…"
        else:
            display_name = agent_user_id[:8] + "…"

        return AgentPerformance(
            agent_user_id=data["agent_user_id"],
            display_name=display_name,
            total_assigned=data["total_assigned"],
            total_resolved=data["total_resolved"],
            total_breached=data["total_breached"],
            avg_resolution_minutes=data["avg_resolution_minutes"],
        )

    # ── Customer report (for LEAD/ADMIN or own) ──────────────────────────────

    async def get_customer_reports(
        self,
        filters: AnalyticsFilters,
        current_user_role: str,
        assignee_ids: Optional[list[str]] = None,
    ) -> list[CustomerTicketReport]:
        """
        Get customer reports.

        Args:
            filters (AnalyticsFilters): Input parameter.
            current_user_role (str): Input parameter.
            assignee_ids (Optional[list[str]]): Team member IDs for team-scoped queries.

        Returns:
            list[CustomerTicketReport]: The expected output.
        """
        role = UserRole(current_user_role)
        if role not in (UserRole.LEAD, UserRole.ADMIN):
            raise InsufficientPermissionsError("Only team leads and admins can view customer reports.")

        rows = await self._analytics_repo.get_customer_reports(
            date_from=filters.date_from,
            date_to=filters.date_to,
            assignee_ids=assignee_ids,
        )
        return [CustomerTicketReport(**r) for r in rows]

    async def get_my_report(
        self,
        current_user_id: str,
    ) -> CustomerTicketReport:
        """
        Get my report.
        
        Args:
            current_user_id (str): Input parameter.
        
        Returns:
            CustomerTicketReport: The expected output.
        """
        data = await self._analytics_repo.get_my_summary(current_user_id)
        return CustomerTicketReport(**data)