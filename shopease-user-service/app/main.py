"""Application entry point: builds the FastAPI app and registers routes.

Run with:  uvicorn app.main:app --reload --port 8002

Routing: settings.api_prefix ("/api") + the router's own prefix ("/users")
= /api/users. Routers only handle HTTP; business logic lives in app/services.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import get_auth_client
from app.database.connection import check_database_connection, engine, get_db
from app.exception_handlers import register_exception_handlers
from app.routers import account_routes, address_routes, user_routes
from app.schemas.user_schema import DatabaseHealthResponse, HealthResponse, RootResponse

settings = get_settings()

logging.basicConfig(level=settings.log_level.upper(),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def _close_connections_on_shutdown(_app: FastAPI) -> AsyncIterator[None]:
    yield
    get_auth_client().close()
    engine.dispose()


# debug is deliberately not enabled: in debug mode Starlette sends tracebacks to clients.
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "User microservice for ShopEase: user profiles and saved addresses.\n\n"
        "Tokens are issued and verified by the ShopEase Authentication Service. Log in there, "
        "select **Authorize** on this page, and paste the access token."
    ),
    lifespan=_close_connections_on_shutdown,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

# Addresses and account first: the planned admin route /users/{auth_user_id} would otherwise
# also match /users/addresses and /users/account.
app.include_router(address_routes.router, prefix=settings.api_prefix)
app.include_router(account_routes.router, prefix=settings.api_prefix)
app.include_router(user_routes.router, prefix=settings.api_prefix)
register_exception_handlers(app)


@app.get("/", response_model=RootResponse, tags=["Service"], summary="Service information")
def root():
    return RootResponse(
        service=settings.app_name,
        version=settings.app_version,
        docs_url=app.docs_url,
    )


@app.get("/health", response_model=HealthResponse, tags=["Service"], summary="Health check")
def health():
    return HealthResponse(status="ok", service=settings.app_name, version=settings.app_version)


@app.get(
    "/health/db",
    response_model=DatabaseHealthResponse,
    responses={503: {"description": "Database unavailable"}},
    tags=["Service"],
    summary="Database connectivity check",
)
def database_health(db: Session = Depends(get_db)):
    if not check_database_connection(db):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")
    return DatabaseHealthResponse(status="ok", database="connected")
