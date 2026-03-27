import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import FastAPI, logger
from src.api.middleware.cors import setup_cors
from src.api.middleware.error_handler import register_exception_handlers
from src.api.middleware.logging import StructLogMiddleware
from src.api.rest.routes.health import router as health_router
from src.api.rest.routes.tickets import router as ticket_router
from src.api.rest.routes.keyword_rules import router as keyword_rules_router
from src.api.rest.routes.sla_rules import router as sla_rules_router
from src.api.rest.routes.analytics import router as analytics_router
from src.api.rest.routes.area_of_concern import router as area_of_concern_router
from src.data.clients.postgres_client import engine
from src.data.models.postgres import Base
from src.observability.logging.logger import setup_logging
from src.api.middleware.jwt_middleware import JWTMiddleware
from src.api.rest.routes.notification_routes import router as notification_router
from src.api.rest.routes.tier_routes import router as tier_router
from src.api.rest.routes.agent_skills import router as agent_skills_router
import src.data.models.postgres
from src.api.rest.routes.email_config_routes import router as email_config_router
from src.api.rest.routes.product_routes import router as product_router
from src.api.rest.routes.similarity_routes import router as similarity_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Lifespan.
    
    Args:
        app (FastAPI): Input parameter.
    
    Returns:
        AsyncGenerator[None, None]: The expected output.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        from src.core.services.ticket_similarity_service import get_similarity_service
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, get_similarity_service)
    except Exception:
        pass
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    """
    Create app.
    
    Returns:
        FastAPI: The expected output.
    """
    from src.core.services.notification.adapter import apply_notification_patch
    apply_notification_patch()
    setup_logging()

    app = FastAPI(
        title="Ticketing Genie — Ticketing Service",
        version="1.0.0",
        description=(
            "## Authentication\n"
            "1. Login via **Auth Service** `POST /api/v1/auth/login` to get a token.\n"
            "2. Click **Authorize** here and paste: `Bearer <token>`"
        ),
        lifespan=lifespan,
    )

    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(ticket_router)
    app.include_router(keyword_rules_router)
    app.include_router(sla_rules_router)
    app.include_router(analytics_router)
    app.include_router(area_of_concern_router)
    app.include_router(notification_router)
    app.include_router(tier_router)
    app.include_router(agent_skills_router)
    app.include_router(email_config_router)
    app.include_router(product_router)
    app.include_router(similarity_router)

    app.add_middleware(JWTMiddleware)
    app.add_middleware(StructLogMiddleware)
    setup_cors(app) 

    return app