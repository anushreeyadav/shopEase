"""Authentication Service application entry point.

Run from the repository root:
    uvicorn app.main:app --app-dir services/auth_service --port 8001
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.api import internal, public
from app.config import Settings, get_settings
from app.db import Database
from app.security.keys import SigningKey, load_signing_key
from app.security.tokens import TokenIssuer
from shopease_shared.openapi import configure_openapi
from shopease_shared import build_health_router, configure_logging, install_common
from shopease_shared.security import StaticKeyProvider, TokenVerifier

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, signing_key: SigningKey | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level)
    db = Database.from_settings(settings)
    # Fails fast outside development when no signing key is configured.
    signing_key = signing_key or load_signing_key(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("service starting", extra={"environment": settings.environment})
        yield
        db.dispose()
        logger.info("service stopped")

    app = FastAPI(
        title="ShopEase Authentication Service",
        version=settings.version,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings
    app.state.db = db
    app.state.signing_key = signing_key
    app.state.token_issuer = TokenIssuer(settings, signing_key)
    # auth_service verifies its own tokens with its own public key: no JWKS round trip.
    app.state.token_verifier = TokenVerifier.from_settings(
        settings, StaticKeyProvider({signing_key.kid: signing_key.public_key})
    )

    configure_openapi(
        app,
        description=(
            'Registration, login, token issuing (RS256 JWT + JWKS), refresh-token rotation, logout, password change, roles, and client-credentials service tokens for internal callers.'
            + '\n\nAll errors use the ShopEase envelope (`ErrorResponse`). Every response carries `X-Request-ID`. Public routes (`/api/...`) are reached through the API Gateway on port 8000 with the same paths; `/internal/...` routes are for other services only. Use **Authorize** with an access token from `POST /api/auth/login`. Contracts: `docs/rest_api_notes.md`.'
        ),
        tags=[
            {"name": "auth", "description": "Accounts, sessions and tokens"},
            {"name": "internal", "description": "Service tokens for internal callers"},
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
