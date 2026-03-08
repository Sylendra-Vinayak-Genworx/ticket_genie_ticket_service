"""
JWT Middleware — decodes the Bearer token and injects:
    request.state.user_id   (str — UUID from Auth Service)
    request.state.user_role (str)

Public paths bypass auth entirely.
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
        # Skip auth for public paths
        if _is_public(request.url.path):
            return await call_next(request)

        auth_header: str = request.headers.get("Authorization", "")

        if not auth_header:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Authorization header is missing.",
                    "error_type": "MissingAuthHeader",
                },
            )

        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Authorization header must start with 'Bearer '.",
                    "error_type": "InvalidAuthHeader",
                },
            )

        token = auth_header[len("Bearer "):]

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

        # Validate required claims
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