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
from src.core.services.attachment_service import AttachmentService
from src.core.services.analytics_service import AnalyticsService
from src.core.services.keyword_rule_service import KeywordRuleService
from src.core.services.sla_rule_service import SLARuleManagementService
from src.core.services.ticket_service import TicketService
from src.core.services.notification.unread_notfication_service import UnreadNotificationService
from src.core.services.priority_rule_service import PriorityRuleService

from fastapi import Depends, HTTPException, status

# ── DB session ─────────────────────────────────────────────────────────────
DBSession = Annotated[AsyncSession, Depends(get_db)]

# ── AttachmentService factory ──────────────────────────────────────────────
def get_attachment_service() -> AttachmentService:
    """
    Get attachment service.
    
    Returns:
        AttachmentService: The expected output.
    """
    return AttachmentService()

AttachmentServiceDep = Annotated[AttachmentService, Depends(get_attachment_service)]




# ── Current user context (set by JWT middleware) ────────────────────────────
def get_current_user_id(request: Request) -> str:          
    """
    Get current user id.
    
    Args:
        request (Request): Input parameter.
    
    Returns:
        str: The expected output.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise InvalidTokenError("Missing user context — JWT middleware not applied.")
    return str(user_id)                                   


def get_current_user_role(request: Request) -> str:
    """
    Get current user role.
    
    Args:
        request (Request): Input parameter.
    
    Returns:
        str: The expected output.
    """
    role = getattr(request.state, "user_role", None)
    if not role:
        raise InvalidTokenError("Missing role context — JWT middleware not applied.")
    return str(role)


CurrentUserID   = Annotated[str, Depends(get_current_user_id)]   # FIX: str
CurrentUserRole = Annotated[str, Depends(get_current_user_role)]

def require_admin(
    user_id: CurrentUserID,
    role: CurrentUserRole,
) -> str:
    """
    Ensure the current user has admin privileges.
    Returns the user_id if authorized.
    """
    if role.lower() != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )

    return user_id

# ── TicketService factory ───────────────────────────────────────────────────
def get_ticket_service(db: DBSession) -> TicketService:
    """
    Get ticket service.
    
    Args:
        db (DBSession): Input parameter.
    
    Returns:
        TicketService: The expected output.
    """
    return TicketService(db=db, auth_client=auth_client)

AuthClientDep = Annotated[AuthServiceClient, Depends(lambda: auth_client)]


TicketServiceDep = Annotated[TicketService, Depends(get_ticket_service)]


# ── KeywordRuleService factory ──────────────────────────────────────────────
def get_keyword_rule_service(db: DBSession) -> KeywordRuleService:
    """
    Get keyword rule service.
    
    Args:
        db (DBSession): Input parameter.
    
    Returns:
        KeywordRuleService: The expected output.
    """
    return KeywordRuleService(db=db)


KeywordRuleServiceDep = Annotated[KeywordRuleService, Depends(get_keyword_rule_service)]


# ── SLARuleManagementService factory ────────────────────────────────────────
def get_sla_rule_management_service(db: DBSession) -> SLARuleManagementService:
    """
    Get sla rule management service.
    
    Args:
        db (DBSession): Input parameter.
    
    Returns:
        SLARuleManagementService: The expected output.
    """
    return SLARuleManagementService(db=db)


SLARuleManagementServiceDep = Annotated[SLARuleManagementService, Depends(get_sla_rule_management_service)]


# ── AnalyticsService factory ────────────────────────────────────────────────
def get_analytics_service(db: DBSession) -> AnalyticsService:
    """
    Get analytics service.
    
    Args:
        db (DBSession): Input parameter.
    
    Returns:
        AnalyticsService: The expected output.
    """
    return AnalyticsService(db=db)


AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]

# ── UnreadNotificationService factory ───────────────────────────────────────

def get_unread_notification_service(db: DBSession) -> UnreadNotificationService:
    """
    Get unread notification service.
    
    Args:
        db (DBSession): Input parameter.
    
    Returns:
        UnreadNotificationService: The expected output.
    """
    return UnreadNotificationService(db=db)

UnreadNotificationServiceDep = Annotated[
    UnreadNotificationService, Depends(get_unread_notification_service)
]


# ── PriorityRuleService factory ──────────────────────────────────────────────

def get_priority_rule_service(db: DBSession) -> PriorityRuleService:
    """
    Get priority rule service.

    Args:
        db (DBSession): Input parameter.

    Returns:
        PriorityRuleService: The expected output.
    """
    return PriorityRuleService(db=db)


PriorityRuleServiceDep = Annotated[PriorityRuleService, Depends(get_priority_rule_service)]