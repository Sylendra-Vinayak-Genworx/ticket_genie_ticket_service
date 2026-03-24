import asyncio
from typing import AsyncGenerator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from src.api.rest.dependencies import CurrentUserID, UnreadNotificationServiceDep
from src.core.services.notification.sse_service import sse_bus
from src.schemas.notification_schema import UnreadNotificationsResponse

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/stream")
async def notification_stream(user_id: CurrentUserID) -> StreamingResponse:
    """SSE endpoint for streaming notifications to the client. Keeps the connection open and sends events as they arrive."""
    async def generator() -> AsyncGenerator[str, None]:
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


@router.get("/connected")
async def is_connected(user_id: CurrentUserID) -> dict:
    return {"connected": sse_bus.is_connected(user_id)}


@router.get("/unread", response_model=UnreadNotificationsResponse)
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
    Returns persisted IN_APP notifications for the current user sent within
    ``since_hours``. Called by the frontend on SSE reconnect to backfill
    any events missed while the user was offline.
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
 