from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from src.api.rest.dependencies import (
    CurrentUserID,
    CurrentUserRole,
    TicketServiceDep,
)
from src.constants.enum import Priority, Severity, TicketStatus

from src.schemas.common_schema import PaginatedResponse
from src.schemas.ticket_schema import (
    CommentCreateRequest,
    CommentResponse,
    TicketAssignRequest,
    TicketBriefResponse,
    TicketCreateRequest,
    TicketDetailResponse,
    TicketListFilters,
    TicketStatusUpdateRequest,
)

from src.data.models.postgres.ticket_comment import TicketComment
router = APIRouter(prefix="/tickets", tags=["tickets"])


def _enqueue_auto_assign(ticket_id: int, ticket_title: str) -> None:
    """
    Thin wrapper so BackgroundTasks can call this after the HTTP response
    is sent (i.e. after get_db() has committed the transaction).
    By the time this runs the ticket row is guaranteed to be visible to
    the Celery worker's independent DB session.
    """
    import logging
    from src.core.tasks.assignment_task import auto_assign_ticket
    auto_assign_ticket.delay(ticket_id=ticket_id, ticket_title=ticket_title)
    logging.getLogger(__name__).info(
        "auto_assign_ticket: enqueued post-commit for ticket_id=%s", ticket_id
    )


@router.post(
    "",
    response_model=TicketDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new ticket",
)
async def create_ticket(
    payload: TicketCreateRequest,
    background_tasks: BackgroundTasks,
    svc: TicketServiceDep,
    user_id: CurrentUserID,
):
    ticket = await svc.create_ticket(payload, current_user_id=user_id)
    # Enqueue AFTER this handler returns — get_db() commits the session
    # in its finally block before BackgroundTasks run, so the worker is
    # guaranteed to find the ticket already committed.
    background_tasks.add_task(
        _enqueue_auto_assign, ticket.ticket_id, ticket.title
    )
    return TicketDetailResponse.model_validate(ticket)


@router.get(
    "/me",
    response_model=PaginatedResponse[TicketBriefResponse],
    summary="Get my tickets — role-aware",
    description=(
        "**user** → tickets they raised  \n"
        "**support_agent** → tickets assigned to them  \n"
        "**team_lead / admin** → all tickets"
    ),
)
async def get_my_tickets(
    svc: TicketServiceDep,
    user_id: CurrentUserID,
    user_role: CurrentUserRole,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: Optional[TicketStatus] = Query(default=None, alias="status"),
    severity: Optional[Severity] = Query(default=None),
    priority: Optional[Priority] = Query(default=None),
    is_breached: Optional[bool] = Query(default=None),
    is_escalated: Optional[bool] = Query(default=None),
    is_unassigned: Optional[bool] = Query(default=None),
    queue_type: Optional[str] = Query(default=None),
):
    filters = TicketListFilters(
        page=page,
        page_size=page_size,
        status=status_filter,
        severity=severity,
        priority=priority,
        is_breached=is_breached,
        is_escalated=is_escalated,
        is_unassigned=is_unassigned,
        queue_type=queue_type,
    )
    total, tickets = await svc.get_my_tickets(
        current_user_id=user_id,
        current_user_role=user_role,
        filters=filters,
    )
    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[TicketBriefResponse.model_validate(t) for t in tickets],
    )


@router.get(
    "",
    response_model=PaginatedResponse[TicketBriefResponse],
    summary="List all tickets — team_lead / admin only",
)
async def list_all_tickets(
    svc: TicketServiceDep,
    user_id: CurrentUserID,
    user_role: CurrentUserRole,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: Optional[TicketStatus] = Query(default=None, alias="status"),
    severity: Optional[Severity] = Query(default=None),
    priority: Optional[Priority] = Query(default=None),
    is_breached: Optional[bool] = Query(default=None),
    is_escalated: Optional[bool] = Query(default=None),
    is_unassigned: Optional[bool] = Query(default=None),
    customer_id: Optional[str] = Query(default=None),
    assignee_id: Optional[str] = Query(default=None),
    team_id: Optional[str] = Query(default=None),
    queue_type: Optional[str] = Query(default=None),
    routing_status: Optional[str] = Query(default=None),
):
    filters = TicketListFilters(
        page=page,
        page_size=page_size,
        status=status_filter,
        severity=severity,
        priority=priority,
        is_breached=is_breached,
        is_escalated=is_escalated,
        is_unassigned=is_unassigned,
        customer_id=customer_id,
        assignee_id=assignee_id,
        team_id=team_id,
        queue_type=queue_type,
        routing_status=routing_status,
    )
    total, tickets = await svc.get_all_tickets(
        filters=filters,
        current_user_role=user_role,
    )
    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[TicketBriefResponse.model_validate(t) for t in tickets],
    )



@router.get(
    "/{ticket_id}",
    response_model=TicketDetailResponse,
    summary="Get ticket detail",
)
async def get_ticket(
    ticket_id: int,
    svc: TicketServiceDep,
    user_id: CurrentUserID,
    user_role: CurrentUserRole,
):
    ticket = await svc.get_ticket_detail(
        ticket_id=ticket_id,
        current_user_id=user_id,
        current_user_role=user_role,
    )
    return TicketDetailResponse.model_validate(ticket)


@router.put(
    "/{ticket_id}/status",
    response_model=TicketBriefResponse,
    summary="Transition ticket status",
)
async def update_ticket_status(
    ticket_id: int,
    payload: TicketStatusUpdateRequest,
    svc: TicketServiceDep,
    user_id: CurrentUserID,
    user_role: CurrentUserRole,
):
    ticket = await svc.transition_status(
        ticket_id, payload,
        current_user_id=user_id,
        current_user_role=user_role,
    )
    return TicketBriefResponse.model_validate(ticket)


@router.post(
    "/{ticket_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a comment to a ticket",
    description=(
        "Post a comment. Agents/leads/admins can pass special flags:\n\n"
        "- **triggers_hold=true** → ticket transitions to **ON_HOLD**, SLA timer **pauses**.\n"
        "- **triggers_resume=true** → ticket transitions to **IN_PROGRESS**, SLA timer **resumes**.\n\n"
        "Both flags cannot be true simultaneously. "
        "Plain comments (both false) are allowed by all roles."
    ),
)
async def add_comment(
    svc: TicketServiceDep,
    payload: CommentCreateRequest,
    user_id: CurrentUserID,
    user_role: CurrentUserRole,
):
    comment = await svc.add_comment(
        payload,
        current_user_id=user_id,
        current_user_role=user_role,
    )
    return CommentResponse.model_validate(comment)


@router.post(
    "/{ticket_id}/assign",
    response_model=TicketBriefResponse,
    summary="Assign ticket to an agent",
)
async def assign_ticket(
    ticket_id: int,
    payload: TicketAssignRequest,
    svc: TicketServiceDep,
    user_id: CurrentUserID,
    user_role: CurrentUserRole,
):
    ticket = await svc.assign_ticket(
        ticket_id, payload,
        current_user_id=user_id,
        current_user_role=user_role,
    )
    return TicketBriefResponse.model_validate(ticket)