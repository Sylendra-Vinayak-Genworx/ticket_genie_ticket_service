from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.core.exceptions.base import TicketingGenieBaseException


def register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers for the application."""

    @app.exception_handler(TicketingGenieBaseException)
    async def application_error_handler(
        request: Request,
        exc: TicketingGenieBaseException,
    ) -> JSONResponse:
        """Handle all custom application errors."""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail
            },
            
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        """Catch-all handler for unexpected errors."""
        import logging
        logger = logging.getLogger("src.api.middleware.error_handler")
        
        request_id = getattr(request.state, "request_id", "unknown")
        logger.error(
            "Unhandled exception: %s [request_id=%s]", 
            str(exc), request_id, 
            exc_info=True
        )
        
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error",
                "request_id": request_id
            },
        )
