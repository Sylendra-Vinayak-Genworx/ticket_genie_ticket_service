"""
FastAPI dependency injection.
JWT is already validated upstream by middleware.
current_user_id + current_user_role are injected via request.state.
"""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.clients.auth_client import auth_client, AuthServiceClient
from src.core.exceptions.base import InvalidTokenError
from src.data.clients.postgres_client import get_db
from src.core.services.analytics_service import AnalyticsService
from src.core.services.keyword_rule_service import KeywordRuleService
from src.core.services.sla_rule_service import SLARuleManagementService
from src.core.services.ticket_service import TicketService


# ── DB session ─────────────────────────────────────────────────────────────
DBSession = Annotated[AsyncSession, Depends(get_db)]


# ── Current user context (set by JWT middleware) ────────────────────────────
def get_current_user_id(request: Request) -> str:          
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise InvalidTokenError("Missing user context — JWT middleware not applied.")
    return str(user_id)                                   


def get_current_user_role(request: Request) -> str:
    role = getattr(request.state, "user_role", None)
    if not role:
        raise InvalidTokenError("Missing role context — JWT middleware not applied.")
    return str(role)


CurrentUserID   = Annotated[str, Depends(get_current_user_id)]   # FIX: str
CurrentUserRole = Annotated[str, Depends(get_current_user_role)]


# ── TicketService factory ───────────────────────────────────────────────────
def get_ticket_service(db: DBSession) -> TicketService:
    return TicketService(db=db, auth_client=auth_client)

AuthClientDep = Annotated[AuthServiceClient, Depends(lambda: auth_client)]


TicketServiceDep = Annotated[TicketService, Depends(get_ticket_service)]


# ── KeywordRuleService factory ──────────────────────────────────────────────
def get_keyword_rule_service(db: DBSession) -> KeywordRuleService:
    return KeywordRuleService(db=db)


KeywordRuleServiceDep = Annotated[KeywordRuleService, Depends(get_keyword_rule_service)]


# ── SLARuleManagementService factory ────────────────────────────────────────
def get_sla_rule_management_service(db: DBSession) -> SLARuleManagementService:
    return SLARuleManagementService(db=db)


SLARuleManagementServiceDep = Annotated[SLARuleManagementService, Depends(get_sla_rule_management_service)]


# ── AnalyticsService factory ────────────────────────────────────────────────
def get_analytics_service(db: DBSession) -> AnalyticsService:
    return AnalyticsService(db=db)


AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]