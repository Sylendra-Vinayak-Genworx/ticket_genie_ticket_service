import time
import uuid
from typing import Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)


class StructLogMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that emits one structured log entry per request.

    Binds a `request_id` to structlog's context-vars so every log line
    produced inside the same request automatically carries the ID.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())
        start = time.perf_counter()

        # Bind request-scoped fields into structlog's async context so all
        # downstream log calls (services, repos, …) carry the same request_id.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        # Expose the request_id on the Starlette request state so route
        # handlers can forward it in response headers if desired.
        request.state.request_id = request_id

        status_code = 500
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
        except Exception:
            logger.exception("unhandled_exception")
            raise
        finally:
            duration_ms = round((time.perf_counter() - start) * 1_000, 2)
            log = logger.info if status_code < 400 else (
                logger.warning if status_code < 500 else logger.error
            )
            log(
                "request_complete",
                status_code=status_code,
                duration_ms=duration_ms,
            )
            structlog.contextvars.clear_contextvars()

        response.headers["X-Request-ID"] = request_id
        return response