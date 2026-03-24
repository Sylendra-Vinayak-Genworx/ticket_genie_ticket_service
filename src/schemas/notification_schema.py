from __future__ import annotations
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict


class NotificationType(str, Enum):
    # Customer-facing
    TICKET_CREATED   = "TICKET_CREATED"
    STATUS_CHANGED   = "STATUS_CHANGED"
    AGENT_COMMENT    = "AGENT_COMMENT"
    AUTO_CLOSED      = "AUTO_CLOSED"

    # Agent-facing
    TICKET_ASSIGNED  = "TICKET_ASSIGNED"
    CUSTOMER_COMMENT = "CUSTOMER_COMMENT"

    # Lead-facing
    SLA_BREACHED = "SLA_BREACHED"


# ── Base ───────────────────────────────────────────────────────────────────────

class _NotificationBase(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticket_id: int
    ticket_number: str
    ticket_title: str


# ── Request models ─────────────────────────────────────────────────────────────

class TicketCreatedRequest(_NotificationBase):
    type: Literal[NotificationType.TICKET_CREATED] = NotificationType.TICKET_CREATED
    customer_id: str


class StatusChangedRequest(_NotificationBase):
    type: Literal[NotificationType.STATUS_CHANGED] = NotificationType.STATUS_CHANGED
    old_status: str
    new_status: str
    severity: str
    customer_id: str
    agent_name: Optional[str] = None


class AgentCommentRequest(_NotificationBase):
    """
    Agent posted a public comment on an EMAIL-source ticket.
    EmailNotificationService renders comment_body directly into the email template.
    """
    type: Literal[NotificationType.AGENT_COMMENT] = NotificationType.AGENT_COMMENT
    status: str
    severity: str
    customer_id: str
    agent_name: str
    comment_body: str
    history: Optional[str] = None


class CustomerCommentRequest(_NotificationBase):
    """Customer replied — notify the assigned agent."""
    type: Literal[NotificationType.CUSTOMER_COMMENT] = NotificationType.CUSTOMER_COMMENT
    customer_name: str
    comment_body: str
    assignee_id: str


class TicketAssignedRequest(_NotificationBase):
    """Ticket assigned — notify the agent or lead."""
    type: Literal[NotificationType.TICKET_ASSIGNED] = NotificationType.TICKET_ASSIGNED
    severity: str
    status: str
    customer_name: str
    assignee_id: str


class SLABreachedRequest(_NotificationBase):
    """SLA breached — escalation alert to the lead."""
    type: Literal[NotificationType.SLA_BREACHED] = NotificationType.SLA_BREACHED
    severity: str
    status: str
    customer_name: str
    breach_type: str          # "response" or "resolution"
    lead_id: str


class AutoClosedRequest(_NotificationBase):
    type: Literal[NotificationType.AUTO_CLOSED] = NotificationType.AUTO_CLOSED
    customer_id: str


# ── Union type ─────────────────────────────────────────────────────────────────

NotificationRequest = (
    TicketCreatedRequest
    | StatusChangedRequest
    | AgentCommentRequest
    | CustomerCommentRequest
    | TicketAssignedRequest
    | SLABreachedRequest
    | AutoClosedRequest
)


# ── Unread backfill response ──────────────────────────────────────────────────
 
class UnreadNotificationsResponse(BaseModel):
    """
    Response for GET /notifications/unread.
    ``notifications`` is an ordered list of SSE payload dicts (newest first)
    that the frontend dispatches directly into notificationsSlice.
    """
    model_config = ConfigDict(frozen=True)
 
    notifications: list[dict]
    count: int
    since_hours: int