from typing import Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, UploadFile, File, status
from src.api.rest.dependencies import (
    CurrentUserID,
    CurrentUserRole,
    TicketServiceDep,
    AttachmentServiceDep,
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



"""Ticket-related endpoints: create ticket, get my tickets, get ticket detail, update status, add comment, assign ticket, upload attachments, self-escalation, etc."""
@router.post(
    "",
    response_model=TicketDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new ticket",
    description="Create a newly formed ticket in the system.",
)
async def create_ticket(
    payload: TicketCreateRequest,
    background_tasks: BackgroundTasks,
    svc: TicketServiceDep,
    user_id: CurrentUserID,
) -> TicketDetailResponse:
    """
    Create ticket.
    
    Args:
        payload (TicketCreateRequest): Input parameter.
        background_tasks (BackgroundTasks): Input parameter.
        svc (TicketServiceDep): Input parameter.
        user_id (CurrentUserID): Input parameter.
    
    Returns:
        TicketDetailResponse: The expected output.
    """
    ticket = await svc.create_ticket(payload, current_user_id=user_id)
    background_tasks.add_task(
        svc.enqueue_auto_assign, ticket.ticket_id, ticket.title
    )
    return TicketDetailResponse.model_validate(ticket)

"""Get my tickets with optional filters. The results are role-aware: customers see their own raised tickets, agents see tickets assigned to them, leads/admins see all tickets. Supports filtering by status, severity, priority, breach/escalation/unassigned flags, queue type, etc., and includes pagination."""
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
) -> PaginatedResponse[TicketBriefResponse]:
    """
    Get my tickets.
    
    Args:
        svc (TicketServiceDep): Input parameter.
        user_id (CurrentUserID): Input parameter.
        user_role (CurrentUserRole): Input parameter.
        page (int): Input parameter.
        page_size (int): Input parameter.
        status_filter (Optional[TicketStatus]): Input parameter.
        severity (Optional[Severity]): Input parameter.
        priority (Optional[Priority]): Input parameter.
        is_breached (Optional[bool]): Input parameter.
        is_escalated (Optional[bool]): Input parameter.
        is_unassigned (Optional[bool]): Input parameter.
        queue_type (Optional[str]): Input parameter.
    
    Returns:
        PaginatedResponse[TicketBriefResponse]: The expected output.
    """
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

"""List all tickets with optional filters. Only accessible by team_lead or admin roles. Supports filtering by status, severity, priority, breach/escalation/unassigned flags, customer/assignee/team IDs, queue type, routing status, etc., and includes pagination."""
@router.get(
    "",
    response_model=PaginatedResponse[TicketBriefResponse],
    summary="List all tickets — team_lead / admin only",
    description="Retrieve a paginated list of all tickets with optional filtering.",
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
) -> PaginatedResponse[TicketBriefResponse]:
    """
    List all tickets.
    
    Args:
        svc (TicketServiceDep): Input parameter.
        user_id (CurrentUserID): Input parameter.
        user_role (CurrentUserRole): Input parameter.
        page (int): Input parameter.
        page_size (int): Input parameter.
        status_filter (Optional[TicketStatus]): Input parameter.
        severity (Optional[Severity]): Input parameter.
        priority (Optional[Priority]): Input parameter.
        is_breached (Optional[bool]): Input parameter.
        is_escalated (Optional[bool]): Input parameter.
        is_unassigned (Optional[bool]): Input parameter.
        customer_id (Optional[str]): Input parameter.
        assignee_id (Optional[str]): Input parameter.
        team_id (Optional[str]): Input parameter.
        queue_type (Optional[str]): Input parameter.
        routing_status (Optional[str]): Input parameter.
    
    Returns:
        PaginatedResponse[TicketBriefResponse]: The expected output.
    """
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

"""Get ticket details by ID. The response includes all ticket fields plus the comment history. Access is role-aware: customers can only access their own tickets, agents can only access tickets assigned to them, leads/admins can access all tickets."""
@router.get(
    "/{ticket_id}",
    response_model=TicketDetailResponse,
    summary="Get ticket detail",
    description="Retrieve the full details of a specific ticket.",
)
async def get_ticket(
    ticket_id: int,
    svc: TicketServiceDep,
    user_id: CurrentUserID,
    user_role: CurrentUserRole,
) -> TicketDetailResponse:
    """
    Get ticket.
    
    Args:
        ticket_id (int): Input parameter.
        svc (TicketServiceDep): Input parameter.
        user_id (CurrentUserID): Input parameter.
        user_role (CurrentUserRole): Input parameter.
    
    Returns:
        TicketDetailResponse: The expected output.
    """
    ticket = await svc.get_ticket_detail(
        ticket_id=ticket_id,
        current_user_id=user_id,
        current_user_role=user_role,
    )
    return TicketDetailResponse.model_validate(ticket)

"""Transition ticket status. The allowed status transitions depend on the current status and the user's role. For example, an agent might be able to move a ticket from "open" to "in_progress", but only a lead/admin can move it to "closed". The service layer will enforce these rules and return an error if an invalid transition is attempted."""
@router.put(
    "/{ticket_id}/status",
    response_model=TicketBriefResponse,
    summary="Transition ticket status",
    description="Transition the primary status of a specific ticket.",
)
async def update_ticket_status(
    ticket_id: int,
    payload: TicketStatusUpdateRequest,
    svc: TicketServiceDep,
    user_id: CurrentUserID,
    user_role: CurrentUserRole,
) -> TicketBriefResponse:
    """
    Update ticket status.
    
    Args:
        ticket_id (int): Input parameter.
        payload (TicketStatusUpdateRequest): Input parameter.
        svc (TicketServiceDep): Input parameter.
        user_id (CurrentUserID): Input parameter.
        user_role (CurrentUserRole): Input parameter.
    
    Returns:
        TicketBriefResponse: The expected output.
    """
    ticket = await svc.transition_status(
        ticket_id, payload,
        current_user_id=user_id,
        current_user_role=user_role,
    )
    return TicketBriefResponse.model_validate(ticket)

"""Add a comment to a ticket. Agents/leads/admins can pass special flags in the request body to indicate if the comment should trigger certain actions, such as notifying the assignee, escalating the ticket, or adding an internal note that is not visible to the customer. The service layer will handle these flags and perform the corresponding actions."""
@router.post(
    "/{ticket_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a comment to a ticket",
    description=(
        "Post a comment. Agents/leads/admins can pass special flags:\n\n"
    ),
)
async def add_comment(
    svc: TicketServiceDep,
    payload: CommentCreateRequest,
    user_id: CurrentUserID,
    user_role: CurrentUserRole,
) -> CommentResponse:
    """
    Add comment.
    
    Args:
        svc (TicketServiceDep): Input parameter.
        payload (CommentCreateRequest): Input parameter.
        user_id (CurrentUserID): Input parameter.
        user_role (CurrentUserRole): Input parameter.
    
    Returns:
        CommentResponse: The expected output.
    """
    comment = await svc.add_comment(
        payload,
        current_user_id=user_id,
        current_user_role=user_role,
    )
    return CommentResponse.from_orm_signed(comment)

"""Assign a ticket to an agent. Only accessible by team_lead or admin roles. The request body includes the ID of the agent to assign to, and optionally a flag to indicate if the ticket should be auto-escalated to the"""
@router.post(
    "/{ticket_id}/assign",
    response_model=TicketBriefResponse,
    summary="Assign ticket to an agent",
    description="Manually assign a ticket to a particular support agent.",
)
async def assign_ticket(
    ticket_id: int,
    payload: TicketAssignRequest,
    svc: TicketServiceDep,
    user_id: CurrentUserID,
    user_role: CurrentUserRole,
) -> TicketBriefResponse:
    """
    Assign ticket.
    
    Args:
        ticket_id (int): Input parameter.
        payload (TicketAssignRequest): Input parameter.
        svc (TicketServiceDep): Input parameter.
        user_id (CurrentUserID): Input parameter.
        user_role (CurrentUserRole): Input parameter.
    
    Returns:
        TicketBriefResponse: The expected output.
    """
    ticket = await svc.assign_ticket(
        ticket_id, payload,
        current_user_id=user_id,
        current_user_role=user_role,
    )
    return TicketBriefResponse.model_validate(ticket)

"""Upload a comment image/attachment to GCS. This endpoint can be used to upload files that will be attached to a comment. The file is first uploaded to GCS, and a signed URL is returned in the response. The client can then use this signed URL to attach the file to a comment when posting the comment content."""
@router.post(
    "/comments/attachments/upload",
    response_model=dict,
    summary="Upload a comment image/attachment to GCS",
    description=(
        "Upload an image or file to attach to a comment. "
    ),
    status_code=status.HTTP_201_CREATED,
)
async def upload_comment_attachment(
    attachment_svc: AttachmentServiceDep,
    file: UploadFile = File(...),
    user_id: CurrentUserID = None,
) -> dict:
    """
    Upload comment attachment.
    
    Args:
        attachment_svc (AttachmentServiceDep): Input parameter.
        file (UploadFile): Input parameter.
        user_id (CurrentUserID): Input parameter.
    
    Returns:
        dict: The expected output.
    """
    return await attachment_svc.upload_comment_attachment(file, user_id)

"""Ticket self-escalation endpoint. Allows a user to manually escalate their ticket to the lead's team if they feel it's not being addressed in a timely manner. The user can provide an optional reason for escalation, which will be recorded in the ticket's history. The service layer will handle the escalation logic, such as changing the ticket's assigned team to the lead's team, updating the ticket status if necessary, and logging the escalation reason."""
@router.post(
    "/attachments/upload",
    response_model=dict,
    summary="Upload a ticket attachment to GCS",
    description=(
        "Upload a file before (or after) creating a ticket. "
    ),
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    attachment_svc: AttachmentServiceDep,
    file: UploadFile = File(...),
    user_id: CurrentUserID = None,
) -> dict:
    """
    Upload attachment.
    
    Args:
        attachment_svc (AttachmentServiceDep): Input parameter.
        file (UploadFile): Input parameter.
        user_id (CurrentUserID): Input parameter.
    
    Returns:
        dict: The expected output.
    """
    return await attachment_svc.upload_ticket_attachment(file, user_id)

@router.post(
    "/{ticket_id}/escalate",
    response_model=TicketBriefResponse,
    summary="Manually escalate a ticket to the lead's team",
    description="Escalate a ticket directly to the lead of the current group.",
)
async def self_escalate_ticket(
    ticket_id: int,
    svc: TicketServiceDep,
    user_id: CurrentUserID,
    user_role: CurrentUserRole,
    reason: str = Query(default=None, description="Reason for manual escalation"),
) -> TicketBriefResponse:
    """
    Self escalate ticket.
    
    Args:
        ticket_id (int): Input parameter.
        svc (TicketServiceDep): Input parameter.
        user_id (CurrentUserID): Input parameter.
        user_role (CurrentUserRole): Input parameter.
        reason (str): Input parameter.
    
    Returns:
        TicketBriefResponse: The expected output.
    """
    ticket = await svc.self_escalate(
        ticket_id=ticket_id,
        reason=reason,
        current_user_id=user_id,
        current_user_role=user_role,
    )
    return TicketBriefResponse.model_validate(ticket)