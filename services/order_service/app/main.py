"""Order Service application entry point.

Run from the repository root:
    uvicorn app.main:app --app-dir services/order_service --port 8004
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from sqlalchemy.exc import InterfaceError, OperationalError
from starlette.concurrency import run_in_threadpool

from app.api import internal, public
from app.config import Settings, get_settings
from app.db import Database
from app.clients import ServiceClients
from app.orders import recover
from shopease_shared.openapi import configure_openapi
from shopease_shared import build_health_router, configure_logging, install_common
from shopease_shared.errors import error_response
from shopease_shared.request_id import new_request_id, request_id_var
from shopease_shared.security import KeyProvider, TokenVerifier

logger = logging.getLogger(__name__)


async def _recovery_loop(app: FastAPI, interval: int) -> None:
    """Expire unpaid orders, clean up abandoned ones, retry pending stock releases."""
    while True:
        await asyncio.sleep(interval)
        request_id_var.set(new_request_id())
        try:
            def run() -> None:
                with app.state.db.session() as session:
                    recover(session, app.state.clients, app.state.settings)

            await run_in_threadpool(run)
        except (OperationalError, InterfaceError) as exc:
            # Expected while the database restarts; the next run retries.
            logger.warning("database unavailable for background job; will retry", extra={"error": type(exc).__name__})
        except Exception:
            logger.exception("order recovery failed; will retry")


def create_app(
    settings: Settings | None = None,
    key_provider: KeyProvider | None = None,
    transport: httpx.BaseTransport | None = None,
) -> FastAPI:
    """`key_provider` and `transport` replace the JWKS fetch and the network in tests."""
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level)
    db = Database.from_settings(settings)
    # One pooled client for product/user/auth calls; per-call timeouts are set in app/clients.py.
    http = httpx.Client(transport=transport, follow_redirects=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("service starting", extra={"environment": settings.environment})
        job = asyncio.create_task(_recovery_loop(app, settings.sweep_seconds)) if settings.sweep_seconds else None
        yield
        if job is not None:
            job.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await job
        http.close()
        db.dispose()
        logger.info("service stopped")

    app = FastAPI(
        title="ShopEase Order Service",
        version=settings.version,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings
    app.state.db = db
    app.state.clients = ServiceClients(settings, http)
    # Verifies tokens locally with auth_service's public keys (JWKS, cached).
    app.state.token_verifier = TokenVerifier.from_settings(settings, key_provider)

    configure_openapi(
        app,
        description=(
            'Orders and checkout coordination: server-side prices, stock reservation, payment results (two-step checkout: pay with `POST /api/payments`), status history and recovery. `POST /api/orders` requires an `Idempotency-Key`. See `docs/order_workflow.md`.'
            + '\n\nAll errors use the ShopEase envelope (`ErrorResponse`). Every response carries `X-Request-ID`. Public routes (`/api/...`) are reached through the API Gateway on port 8000 with the same paths; `/internal/...` routes are for other services only. Use **Authorize** with an access token from `POST /api/auth/login`. Contracts: `docs/rest_api_notes.md`.'
        ),
        tags=[
            {"name": "orders", "description": "Customer orders and admin fulfilment"},
            {"name": "internal", "description": "Payable view and payment results for payment_service"},
            {"name": "health", "description": "Liveness and readiness"},
        ],
    )
    install_common(app)

    async def database_unavailable(request: Request, exc: Exception):
        logger.error("database unavailable", extra={"error": type(exc).__name__})
        return error_response(
            request, 503, "DATABASE_UNAVAILABLE", "The order database is temporarily unavailable.",
            headers={"Retry-After": "5"},
        )

    app.add_exception_handler(OperationalError, database_unavailable)
    app.add_exception_handler(InterfaceError, database_unavailable)
    app.include_router(
        build_health_router(settings, {"database": lambda: run_in_threadpool(db.ping)})
    )
    app.include_router(public.router)
    app.include_router(internal.router)
    return app


app = create_app()
