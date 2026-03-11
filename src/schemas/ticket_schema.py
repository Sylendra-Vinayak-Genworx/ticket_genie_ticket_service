from datetime import datetime, timedelta
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field

from src.constants.enum import (
    Environment,
    EventType,
    NotificationChannel,
    NotificationStatus,
    Priority,
    QueueType,
    RoutingStatus,
    Severity,
    TicketSource,
    TicketStatus,
)
from src.data.models.postgres.ticket_event import TicketEvent


# ── Attachment ────────────────────────────────────────────────────────────────
class AttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attachment_id: int
    ticket_id: int
    file_name: str
    file_url: str
    uploaded_by_user_id: str
    uploaded_at: datetime


# ── Ticket Event ──────────────────────────────────────────────────────────────
class TicketEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: int
    ticket_id: int
    triggered_by_user_id: Optional[str] = None
    event_type: EventType
    field_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    comment_id: Optional[int] = None
    created_at: datetime


# ── Comment ───────────────────────────────────────────────────────────────────
class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    comment_id: int
    ticket_id: int
    author_id: str
    author_role: str
    body: str
    is_internal: bool
    triggers_hold: bool = False
    triggers_resume: bool = False
    attachments: Optional[list] = None
    created_at: datetime


# ── Comment Create ─────────────────────────────────────────────────────────────
class CommentCreateRequest(BaseModel):
    """
    Request body for POST /tickets/{id}/comments.

    Behaviour:
      - triggers_hold=True   → ticket transitions ON_HOLD  + SLA timer pauses.
      - triggers_resume=True → ticket transitions IN_PROGRESS + SLA timer resumes.
      - Both cannot be True simultaneously.
    """
    body: str = Field(..., min_length=1, max_length=5000)
    is_internal: bool = False
    triggers_hold: bool = False
    triggers_resume: bool = False
    ticket_id: int =Field(...)



# ── Create ───────────────────────────────────────────────────────────────────
class TicketCreateRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=500)
    description: str = Field(..., min_length=10)
    product: str = Field(..., min_length=1, max_length=100)
    environment: Environment
    source: TicketSource = TicketSource.UI
    area_of_concern: Optional[int] = Field(default=None)   # FK → areas_of_concern.area_id
    attachments: list[str] = Field(default_factory=list)


# ── Status transition ─────────────────────────────────────────────────────────
class TicketStatusUpdateRequest(BaseModel):
    new_status: TicketStatus
    comment: Optional[str] = Field(default=None, max_length=2000)


# ── Assign ────────────────────────────────────────────────────────────────────
class TicketAssignRequest(BaseModel):
    assignee_id: str = Field(...)


# ── Brief response (list view) ────────────────────────────────────────────────
class TicketBriefResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticket_id: int
    ticket_number: str
    title: str
    status: TicketStatus
    severity: Severity
    priority: Priority
    environment: Environment
    product: str
    area_of_concern: Optional[int] = None
    source: TicketSource
    customer_id: str
    assignee_id: Optional[str] = None
    assigned_agent_id: Optional[int] = None
    queue_type: str = QueueType.DIRECT.value
    routing_status: str = RoutingStatus.SUCCESS.value
    sla_id: Optional[int] = None
    customer_tier_id: Optional[int] = None
    is_breached: bool = False
    is_escalated: bool = False
    escalation_level: int = 0
    created_at: datetime
    updated_at: datetime

    # Raw SLA fields needed to compute due timestamps
    response_sla_started_at: Optional[datetime] = None
    response_sla_deadline_minutes: Optional[int] = None
    response_sla_completed_at: Optional[datetime] = None
    resolution_sla_started_at: Optional[datetime] = None
    resolution_sla_deadline_minutes: Optional[int] = None
    resolution_sla_total_pause_duration: int = 0
    resolution_sla_completed_at: Optional[datetime] = None

    @computed_field
    @property
    def response_due_at(self) -> Optional[datetime]:
        if self.response_sla_started_at and self.response_sla_deadline_minutes:
            return self.response_sla_started_at + timedelta(minutes=self.response_sla_deadline_minutes)
        return None

    @computed_field
    @property
    def resolution_due_at(self) -> Optional[datetime]:
        if self.resolution_sla_started_at and self.resolution_sla_deadline_minutes:
            effective = self.resolution_sla_deadline_minutes + (self.resolution_sla_total_pause_duration or 0)
            return self.resolution_sla_started_at + timedelta(minutes=effective)
        return None


# ── Detail response (single ticket) ──────────────────────────────────────────
class TicketDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticket_id: int
    ticket_number: str
    title: str
    description: str
    product: str
    environment: Environment
    area_of_concern: Optional[int] = None
    source: TicketSource
    severity: Severity
    priority: Priority
    status: TicketStatus
    customer_id: str
    assignee_id: Optional[str] = None
    assigned_agent_id: Optional[int] = None
    queue_type: str = QueueType.DIRECT.value
    routing_status: str = RoutingStatus.SUCCESS.value
    sla_id: Optional[int] = None
    customer_tier_id: Optional[int] = None
    is_breached: bool = False
    is_escalated: bool = False
    hold_started_at: Optional[datetime] = None
    total_hold_minutes: int = 0
    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    # Raw SLA fields needed to compute due timestamps
    response_sla_started_at: Optional[datetime] = None
    response_sla_deadline_minutes: Optional[int] = None
    response_sla_completed_at: Optional[datetime] = None
    resolution_sla_started_at: Optional[datetime] = None
    resolution_sla_deadline_minutes: Optional[int] = None
    resolution_sla_total_pause_duration: int = 0
    resolution_sla_completed_at: Optional[datetime] = None

    @computed_field
    @property
    def response_due_at(self) -> Optional[datetime]:
        if self.response_sla_started_at and self.response_sla_deadline_minutes:
            return self.response_sla_started_at + timedelta(minutes=self.response_sla_deadline_minutes)
        return None

    @computed_field
    @property
    def resolution_due_at(self) -> Optional[datetime]:
        if self.resolution_sla_started_at and self.resolution_sla_deadline_minutes:
            effective = self.resolution_sla_deadline_minutes + (self.resolution_sla_total_pause_duration or 0)
            return self.resolution_sla_started_at + timedelta(minutes=effective)
        return None

    # Eagerly loaded relations
    events: list[TicketEventResponse] = Field(default_factory=list)
    comments: list[CommentResponse] = Field(default_factory=list)
    attachments: list[AttachmentResponse] = Field(default_factory=list)


# ── Filters (used by list endpoint) ───────────────────────────────────────────
class TicketListFilters(BaseModel):
    status: Optional[TicketStatus] = None
    severity: Optional[Severity] = None
    priority: Optional[Priority] = None
    is_breached: Optional[bool] = None
    is_escalated: Optional[bool] = None
    customer_id: Optional[str] = None   
    assignee_id: Optional[str] = None
    assignee_ids:Optional[list[str]] = None
    page: int = 1
    page_size: int = 20


class TicketTimelineResponse(BaseModel):
    """
    Projects a STATUS_CHANGED TicketEvent as a timeline entry.
    """
    model_config = ConfigDict(from_attributes=True)

    event_id: int
    ticket_id: int
    from_status: Optional[str] = None
    to_status: str
    changed_by: Optional[str] = None
    changed_at: datetime
    reason: Optional[str] = None

    @classmethod
    def from_event(cls, event: "TicketEvent") -> "TicketTimelineResponse":
        return cls(
            event_id=event.event_id,
            ticket_id=event.ticket_id,
            from_status=event.from_status,
            to_status=event.new_value or "",
            changed_by=event.triggered_by_user_id or "SYSTEM",
            changed_at=event.created_at,
            reason=event.reason,
        )