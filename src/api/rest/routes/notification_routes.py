import asyncio
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src.api.rest.dependencies import CurrentUserID
from src.core.services.notification.sse_service import sse_bus

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