"""
api/rest/routes/notifications.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SSE streaming endpoint for UI notifications.

ADD to src/api/rest/app.py:
    from src.api.rest.routes.notifications import router as notifications_router
    app.include_router(notifications_router)
"""

import asyncio
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src.api.rest.dependencies import CurrentUserID
from src.core.services.notification.sse_service import sse_bus

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/stream")
async def notification_stream(user_id: CurrentUserID) -> StreamingResponse:
    """
    SSE stream for the authenticated user.
    Frontend connects once; receives events as they are pushed by NotificationManager.

    Event format:
        data: {"type": "STATUS_CHANGED", "ticket_number": "TKT-0005", ...}\n\n
    """
    async def generator() -> AsyncGenerator[str, None]:
        queue = sse_bus.subscribe(user_id)
        yield ": connected\n\n"
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {event}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"   # keep-alive every 30s
        except asyncio.CancelledError:
            pass
        finally:
            sse_bus.unsubscribe(user_id, queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering
            "Connection": "keep-alive",
        },
    )


@router.get("/connected")
async def is_connected(user_id: CurrentUserID) -> dict:
    """Returns whether the user has an active SSE connection."""
    return {"connected": sse_bus.is_connected(user_id)}