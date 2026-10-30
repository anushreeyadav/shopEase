"""Product Service application entry point.

Run from the repository root:
    uvicorn app.main:app --app-dir services/product_service --port 8003
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from sqlalchemy.exc import InterfaceError, OperationalError
from starlette.concurrency import run_in_threadpool

from app.api import internal, public
from app.config import Settings, get_settings
from app.db import Database
from app.stock import expire_due
from shopease_shared.openapi import configure_openapi
from shopease_shared import build_health_router, configure_logging, install_common
from shopease_shared.errors import error_response
from shopease_shared.request_id import new_request_id, request_id_var
from shopease_shared.security import KeyProvider, TokenVerifier

logger = logging.getLogger(__name__)


async def _sweep_expired_reservations(app: FastAPI, interval: int) -> None:
    """Release reservations whose payment window passed (order_service may never call back)."""
    while True:
        await asyncio.sleep(interval)
        request_id_var.set(new_request_id())
        try:
            def run() -> int:
                with app.state.db.session() as session:
                    return expire_due(session)

            await run_in_threadpool(run)
        except (OperationalError, InterfaceError) as exc:
            # Expected while the database restarts; the next run retries.
            logger.warning("database unavailable for background job; will retry", extra={"error": type(exc).__name__})
        except Exception:
            logger.exception("reservation expiry sweep failed; will retry")


def create_app(settings: Settings | None = None, key_provider: KeyProvider | None = None) -> FastAPI:
    """`key_provider` replaces the JWKS fetch in tests."""
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level)
    db = Database.from_settings(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("service starting", extra={"environment": settings.environment})
        sweeper = None
        if settings.reservation_sweep_seconds:
            sweeper = asyncio.create_task(_sweep_expired_reservations(app, settings.reservation_sweep_seconds))
        yield
        if sweeper is not None:
            sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sweeper
        db.dispose()
        logger.info("service stopped")

    app = FastAPI(
        title="ShopEase Product Service",
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
            'Catalog, categories, prices and inventory. Reads are public; changes need the admin role. Stock reservations for checkout are internal, all-or-nothing, idempotent per order and safe under concurrency; every stock change is audited.'
            + '\n\nAll errors use the ShopEase envelope (`ErrorResponse`). Every response carries `X-Request-ID`. Public routes (`/api/...`) are reached through the API Gateway on port 8000 with the same paths; `/internal/...` routes are for other services only. Use **Authorize** with an access token from `POST /api/auth/login`. Contracts: `docs/rest_api_notes.md`.'
        ),
        tags=[
            {"name": "products", "description": "Catalog, prices and admin inventory"},
            {"name": "categories", "description": "Product categories"},
            {"name": "internal", "description": "Price checks and stock reservations for order_service"},
            {"name": "health", "description": "Liveness and readiness"},
        ],
    )
    install_common(app)

    async def database_unavailable(request: Request, exc: Exception):
        logger.error("database unavailable", extra={"error": type(exc).__name__})
        return error_response(
            request, 503, "DATABASE_UNAVAILABLE", "The product database is temporarily unavailable.",
            headers={"Retry-After": "5"},
        )

    app.add_exception_handler(OperationalError, database_unavailable)
    app.add_exception_handler(InterfaceError, database_unavailable)
    app.include_router(
        build_health_router(settings, {"database": lambda: run_in_threadpool(db.ping)})
    )
    app.include_router(public.router)
    app.include_router(public.categories_router)
    app.include_router(internal.router)
    return app


app = create_app()
