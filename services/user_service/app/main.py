"""User Service application entry point.

Run from the repository root:
    uvicorn app.main:app --app-dir services/user_service --port 8002
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.api import internal, public
from app.config import Settings, get_settings
from app.db import Database
from shopease_shared.openapi import configure_openapi
from shopease_shared import build_health_router, configure_logging, install_common
from shopease_shared.security import KeyProvider, TokenVerifier

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, key_provider: KeyProvider | None = None) -> FastAPI:
    """`key_provider` replaces the JWKS fetch in tests."""
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level)
    db = Database.from_settings(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("service starting", extra={"environment": settings.environment})
        yield
        db.dispose()
        logger.info("service stopped")

    app = FastAPI(
        title="ShopEase User Service",
        version=settings.version,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings
    app.state.db = db
    # Verifies tokens locally with auth_service's public keys (JWKS, cached).
    app.state.token_verifier = TokenVerifier.from_settings(settings, key_provider)

    configure_openapi(
        app,
        description=(
            "Customer profiles (created on first access) and delivery addresses. Every route acts on the caller's own data; admins may read any profile. order_service reads one address internally with a service token plus the customer's forwarded token."
            + '\n\nAll errors use the ShopEase envelope (`ErrorResponse`). Every response carries `X-Request-ID`. Public routes (`/api/...`) are reached through the API Gateway on port 8000 with the same paths; `/internal/...` routes are for other services only. Use **Authorize** with an access token from `POST /api/auth/login`. Contracts: `docs/rest_api_notes.md`.'
        ),
        tags=[
            {"name": "users", "description": "Profile and addresses of the caller"},
            {"name": "internal", "description": "Address lookup for order_service"},
            {"name": "health", "description": "Liveness and readiness"},
        ],
    )
    install_common(app)
    app.include_router(
        build_health_router(settings, {"database": lambda: run_in_threadpool(db.ping)})
    )
    app.include_router(public.router)
    app.include_router(internal.router)
    return app


app = create_app()
