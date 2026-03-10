"""
JWT Middleware — decodes the Bearer token and injects:
    request.state.user_id   (str — UUID from Auth Service)
    request.state.user_role (str)

Public paths bypass auth entirely.
Token is read from the Authorization header first, then from the
?token= query parameter as a fallback (required for EventSource / SSE,
which cannot send custom headers in the browser).
"""

import logging
from typing import Callable

from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Paths that never require a token
_PUBLIC_PATHS: set[str] = {"/health", "/health/", "/docs", "/redoc", "/openapi.json"}
_PUBLIC_PREFIXES: tuple[str, ...] = ("/docs/", "/redoc/")


def _is_public(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True
    return any(path.startswith(p) for p in _PUBLIC_PREFIXES)


class JWTMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next: Callable) -> Response:

        if request.method == "OPTIONS":
            return await call_next(request)

        if _is_public(request.url.path):
            return await call_next(request)

        # Primary: Authorization header
        # Fallback: ?token= query param — required for EventSource (SSE) which
        # cannot send custom headers in the browser.
        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token:
            token = request.query_params.get("token", "").strip()

        if not token:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Authorization header is missing.",
                    "error_type": "MissingAuthHeader",
                },
            )

        try:
            payload = jwt.decode(
                token,
                settings.secret_key,
                algorithms=[settings.algorithm],
            )
        except ExpiredSignatureError:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Access token has expired. Please log in again.",
                    "error_type": "TokenExpired",
                },
            )
        except JWTError as exc:
            logger.warning("jwt_middleware: invalid token — %s", exc)
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Access token is invalid.",
                    "error_type": "InvalidToken",
                },
            )

        user_id = payload.get("sub")
        user_role = payload.get("role")

        if not user_id or not user_role:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Token is missing required claims (sub, role).",
                    "error_type": "MissingClaims",
                },
            )

        request.state.user_id = user_id
        request.state.user_role = str(user_role)

        logger.debug(
            "jwt_middleware: authenticated user_id=%s role=%s path=%s",
            user_id, user_role, request.url.path,
        )

        return await call_next(request)