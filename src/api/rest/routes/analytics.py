from datetime import datetime
from typing import Optional

from typing import List
from fastapi import APIRouter, Query
from src.data.clients.auth_client import AuthServiceClient

from src.api.rest.dependencies import (
    AnalyticsServiceDep,
    AuthClientDep,
    CurrentUserID,
    CurrentUserRole,
)
from src.schemas.analytics_schema import (
    AdminDashboard,
    AgentPerformance,
    AnalyticsFilters,
    CustomerTicketReport,
    SLAComplianceReport,
)


async def _resolve_team_member_ids(lead_id: str, auth: AuthServiceClient) -> list[str]:
    """
    Return user_ids of all agents whose lead_id == lead_id, plus the lead themselves.
    Falls back to [lead_id] on any error so the route still works.
    """
    try:
        all_users = await auth.get_all_users()
        members = [
            u.id for u in all_users
            if u.lead_id == lead_id or u.id == lead_id
        ]
        return members if members else [lead_id]
    except Exception:
        return [lead_id]


router = APIRouter(prefix="/analytics", tags=["analytics"])



def _build_filters(
    date_from: Optional[datetime],
    date_to: Optional[datetime],
    product: Optional[str],
    customer_tier_id: Optional[int],
) -> AnalyticsFilters:
    return AnalyticsFilters(
        date_from=date_from,
        date_to=date_to,
        product=product,
        customer_tier_id=customer_tier_id,
    )

"""Analytics endpoints for Admin/Lead dashboards, SLA compliance, agent performance, etc."""
@router.get(
    "/dashboard",
    response_model=AdminDashboard,
    summary="Admin / Lead dashboard",
    description="Retrieve the analytics dashboard data for admin and lead users.",
)
async def get_dashboard(
    svc: AnalyticsServiceDep,
    auth: AuthClientDep,
    user_id: CurrentUserID,
    user_role: CurrentUserRole,
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    product: Optional[str] = Query(default=None),
    customer_tier_id: Optional[int] = Query(default=None),
) -> AdminDashboard:
    """
    Get dashboard.
    
    Args:
        svc (AnalyticsServiceDep): Input parameter.
        auth (AuthClientDep): Input parameter.
        user_id (CurrentUserID): Input parameter.
        user_role (CurrentUserRole): Input parameter.
        date_from (Optional[datetime]): Input parameter.
        date_to (Optional[datetime]): Input parameter.
        product (Optional[str]): Input parameter.
        customer_tier_id (Optional[int]): Input parameter.
    
    Returns:
        AdminDashboard: The expected output.
    """
    filters = _build_filters(date_from, date_to, product, customer_tier_id)
    # Team leads see only their own team's data
    assignee_ids = None
    if user_role == "team_lead":
        assignee_ids = await _resolve_team_member_ids(user_id, auth)
    return await svc.get_admin_dashboard(
        filters, current_user_role=user_role, assignee_ids=assignee_ids, auth_client=auth
    )

"""SLA compliance report for Admin/Lead dashboards."""
@router.get(
    "/sla-compliance",
    response_model=SLAComplianceReport,
    summary="SLA compliance report (LEAD / ADMIN)",
    description="Retrieve the SLA compliance report for admins and leads.",
)
async def get_sla_compliance(
    svc: AnalyticsServiceDep,
    user_role: CurrentUserRole,
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    product: Optional[str] = Query(default=None),
    customer_tier_id: Optional[int] = Query(default=None),
) -> SLAComplianceReport:
    """
    Get sla compliance.
    
    Args:
        svc (AnalyticsServiceDep): Input parameter.
        user_role (CurrentUserRole): Input parameter.
        date_from (Optional[datetime]): Input parameter.
        date_to (Optional[datetime]): Input parameter.
        product (Optional[str]): Input parameter.
        customer_tier_id (Optional[int]): Input parameter.
    
    Returns:
        SLAComplianceReport: The expected output.
    """
    filters = _build_filters(date_from, date_to, product, customer_tier_id)
    return await svc.get_sla_compliance(filters, current_user_role=user_role)


"""Agent performance report (ticket resolution times, customer satisfaction, etc.) for the agent themselves, or for their team if the requester is a lead."""
@router.get(
    "/agents/{agent_user_id}",
    response_model=AgentPerformance,
    summary="Agent performance (self or LEAD/ADMIN)",
    description="Retrieve the performance metrics for a specific agent.",
)
async def get_agent_performance(
    agent_user_id: str,
    svc: AnalyticsServiceDep,
    auth: AuthClientDep,
    user_id: CurrentUserID,
    user_role: CurrentUserRole,
) -> AgentPerformance:
    """
    Get agent performance.
    
    Args:
        agent_user_id (str): Input parameter.
        svc (AnalyticsServiceDep): Input parameter.
        auth (AuthClientDep): Input parameter.
        user_id (CurrentUserID): Input parameter.
        user_role (CurrentUserRole): Input parameter.
    
    Returns:
        AgentPerformance: The expected output.
    """
    return await svc.get_agent_performance(
        agent_user_id=agent_user_id,
        current_user_id=user_id,
        current_user_role=user_role,
        auth_client=auth,
    )

"""Customer ticket reports (number of tickets, average resolution time, etc.) for the customer themselves, or for all customers if the requester is a lead/admin."""
@router.get(
    "/customers",
    response_model=list[CustomerTicketReport],
    summary="Customer ticket reports (LEAD / ADMIN)",
    description="Retrieve ticket reports and statistics for customers.",
)
async def get_customer_reports(
    svc: AnalyticsServiceDep,
    user_role: CurrentUserRole,
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    product: Optional[str] = Query(default=None),
    customer_tier_id: Optional[int] = Query(default=None),
) -> list[CustomerTicketReport]:
    """
    Get customer reports.
    
    Args:
        svc (AnalyticsServiceDep): Input parameter.
        user_role (CurrentUserRole): Input parameter.
        date_from (Optional[datetime]): Input parameter.
        date_to (Optional[datetime]): Input parameter.
        product (Optional[str]): Input parameter.
        customer_tier_id (Optional[int]): Input parameter.
    
    Returns:
        list[CustomerTicketReport]: The expected output.
    """
    filters = _build_filters(date_from, date_to, product, customer_tier_id)
    return await svc.get_customer_reports(filters, current_user_role=user_role)


"""My tickets" report for customers, showing their own tickets and stats about them."""
@router.get(
    "/me",
    response_model=CustomerTicketReport,
    summary="My own ticket summary",
    description="Retrieve a ticket summary and statistics for the current user.",
)
async def get_my_report(
    svc: AnalyticsServiceDep,
    user_id: CurrentUserID,
) -> CustomerTicketReport:
    """
    Get my report.
    
    Args:
        svc (AnalyticsServiceDep): Input parameter.
        user_id (CurrentUserID): Input parameter.
    
    Returns:
        CustomerTicketReport: The expected output.
    """
    return await svc.get_my_report(current_user_id=user_id)