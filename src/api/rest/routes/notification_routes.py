import asyncio
from typing import AsyncGenerator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from src.api.rest.dependencies import CurrentUserID, UnreadNotificationServiceDep
from src.core.services.notification.sse_service import sse_bus
from src.schemas.notification_schema import UnreadNotificationsResponse

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get(
    "/stream",
    response_model=None,
    summary="Notification stream",
    description="SSE endpoint for streaming notifications to the client.",
)
async def notification_stream(user_id: CurrentUserID) -> StreamingResponse:
    """SSE endpoint for streaming notifications to the client. Keeps the connection open and sends events as they arrive."""
    async def generator() -> AsyncGenerator[str, None]:
        """
        Generator.
        
        Returns:
            AsyncGenerator[str, None]: The expected output.
        """
        queue = await sse_bus.subscribe(user_id)
        yield ": connected\n\n"
        try:
            while True:
                try:
                   
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {event}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            sse_bus.unsubscribe(user_id, queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  
            "Connection": "keep-alive",
        },
    )


@router.get(
    "/connected",
    response_model=dict,
    summary="Check connection status",
    description="Check if the user is currently connected to the notification stream.",
)
async def is_connected(user_id: CurrentUserID) -> dict:
    """
    Is connected.
    
    Args:
        user_id (CurrentUserID): Input parameter.
    
    Returns:
        dict: The expected output.
    """
    return {"connected": sse_bus.is_connected(user_id)}


@router.patch(
    "/read-all",
    response_model=dict,
    summary="Mark all notifications as read",
    description="Updates the status of ALL unread IN_APP notifications for the current user to READ.",
)
async def mark_all_notifications_read(
    user_id: CurrentUserID,
    svc: UnreadNotificationServiceDep,
) -> dict:
    """Mark all notifications as read."""
    count = await svc.mark_all_as_read(user_id=user_id)
    return {"count": count}


@router.get(
    "/unread",
    response_model=UnreadNotificationsResponse,
    summary="Get unread notifications",
    description="Returns persisted IN_APP notifications for the current user.",
)
async def get_unread_notifications(
    user_id: CurrentUserID,
    svc: UnreadNotificationServiceDep,
    since_hours: int = Query(
        default=24,
        ge=1,
        le=168,
        description="How far back to look for missed notifications (hours). Max 7 days.",
    ),
) -> UnreadNotificationsResponse:
    """
    Get unread notifications.
    
    Args:
        user_id (CurrentUserID): Input parameter.
        svc (UnreadNotificationServiceDep): Input parameter.
        since_hours (int): Input parameter.
    
    Returns:
        UnreadNotificationsResponse: The expected output.
    """
    notifications = await svc.get_unread(
        recipient_user_id=user_id,
        since_hours=since_hours,
    )
    return UnreadNotificationsResponse(
        notifications=notifications,
        count=len(notifications),
        since_hours=since_hours,
    )


@router.patch(
    "/{notification_id}/read",
    response_model=dict,
    summary="Mark notification as read",
    description="Updates the status of a specific notification to READ.",
)
async def mark_notification_read(
    notification_id: int,
    user_id: CurrentUserID,
    svc: UnreadNotificationServiceDep,
) -> dict:
    """Mark a notification as read."""
    success = await svc.mark_as_read(user_id=user_id, notification_id=notification_id)
    return {"success": success}


