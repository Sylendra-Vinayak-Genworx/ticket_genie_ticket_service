"""
Analytics / reporting routes.

GET  /analytics/dashboard             Admin/Lead dashboard (aggregated)
GET  /analytics/sla-compliance        SLA compliance report
GET  /analytics/agents/{id}           Agent performance (self or admin/lead)
GET  /analytics/customers             Customer reports (admin/lead)
GET  /analytics/me                    Current user's own report
"""

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


@router.get(
    "/dashboard",
    response_model=AdminDashboard,
    summary="Admin / Lead dashboard",
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
):
    filters = _build_filters(date_from, date_to, product, customer_tier_id)
    # Team leads see only their own team's data
    assignee_ids = None
    if user_role == "team_lead":
        assignee_ids = await _resolve_team_member_ids(user_id, auth)
    return await svc.get_admin_dashboard(
        filters, current_user_role=user_role, assignee_ids=assignee_ids
    )


@router.get(
    "/sla-compliance",
    response_model=SLAComplianceReport,
    summary="SLA compliance report (LEAD / ADMIN)",
)
async def get_sla_compliance(
    svc: AnalyticsServiceDep,
    user_role: CurrentUserRole,
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    product: Optional[str] = Query(default=None),
    customer_tier_id: Optional[int] = Query(default=None),
):
    filters = _build_filters(date_from, date_to, product, customer_tier_id)
    return await svc.get_sla_compliance(filters, current_user_role=user_role)



@router.get(
    "/agents/{agent_user_id}",
    response_model=AgentPerformance,
    summary="Agent performance (self or LEAD/ADMIN)",
)
async def get_agent_performance(
    agent_user_id: str,
    svc: AnalyticsServiceDep,
    user_id: CurrentUserID,
    user_role: CurrentUserRole,
):
    return await svc.get_agent_performance(
        agent_user_id=agent_user_id,
        current_user_id=user_id,
        current_user_role=user_role,
    )


@router.get(
    "/customers",
    response_model=list[CustomerTicketReport],
    summary="Customer ticket reports (LEAD / ADMIN)",
)
async def get_customer_reports(
    svc: AnalyticsServiceDep,
    user_role: CurrentUserRole,
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    product: Optional[str] = Query(default=None),
    customer_tier_id: Optional[int] = Query(default=None),
):
    filters = _build_filters(date_from, date_to, product, customer_tier_id)
    return await svc.get_customer_reports(filters, current_user_role=user_role)



@router.get(
    "/me",
    response_model=CustomerTicketReport,
    summary="My own ticket summary",
)
async def get_my_report(
    svc: AnalyticsServiceDep,
    user_id: CurrentUserID,
):
    return await svc.get_my_report(current_user_id=user_id)