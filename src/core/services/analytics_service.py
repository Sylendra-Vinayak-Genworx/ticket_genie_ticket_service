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

        return AdminDashboard(
            summary=TicketSummary(**summary_data),
            distribution=TicketDistribution(**dist_data),
            sla_compliance=SLAComplianceReport(**sla_data),
            top_agents=top_agents,
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
    ) -> list[CustomerTicketReport]:
        """
        Get customer reports.
        
        Args:
            filters (AnalyticsFilters): Input parameter.
            current_user_role (str): Input parameter.
        
        Returns:
            list[CustomerTicketReport]: The expected output.
        """
        role = UserRole(current_user_role)
        if role not in (UserRole.LEAD, UserRole.ADMIN):
            raise InsufficientPermissionsError("Only team leads and admins can view customer reports.")

        rows = await self._analytics_repo.get_customer_reports(
            date_from=filters.date_from,
            date_to=filters.date_to,
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