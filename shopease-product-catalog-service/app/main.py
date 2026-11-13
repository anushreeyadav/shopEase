"""Application entry point: builds the FastAPI app, registers routes and error handlers.

Run with:  python -m app            (host and port from SERVICE_HOST / SERVICE_PORT)
      or:  uvicorn app.main:app --reload --port 8006

Routing: settings.api_prefix ("/api") + each router's prefix, for example /api/products.
Routers only handle HTTP; business logic lives in app/services.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import get_auth_client
from app.database.connection import check_database_connection, engine, get_db
from app.routers import category_routes, inventory_routes, product_routes
from app.schemas.common_schema import DatabaseHealthResponse, HealthResponse, RootResponse
from app.services.errors import ConflictError, InvalidFieldError, NotFoundError

settings = get_settings()

logging.basicConfig(level=settings.log_level.upper(),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


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
        "Product catalog microservice for ShopEase: categories, products and inventory.\n\n"
        "Browsing is public. Admin operations need a token from the ShopEase Authentication "
        "Service: log in there, select **Authorize** on this page, and paste the access token."
    ),
    lifespan=_close_connections_on_shutdown,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

app.include_router(category_routes.router, prefix=settings.api_prefix)
app.include_router(product_routes.router, prefix=settings.api_prefix)
app.include_router(inventory_routes.router, prefix=settings.api_prefix)


# --- Error handlers: every error has a JSON body, and none leaks internal details ---

def _field_name(error: dict) -> str:
    # loc is ("body" | "query" | "path", "field", ...); a model-level error has only ("body",).
    return ".".join(str(part) for part in error["loc"][1:]) or str(error["loc"][0])


def _message(error: dict) -> str:
    if error["type"] == "extra_forbidden" and error["loc"][0] == "query":
        return "Unknown query parameter"
    return error["msg"].removeprefix("Value error, ")


_NOT_AN_OBJECT = {"model_attributes_type", "dict_type"}


def _malformed_body(errors: list[dict]) -> str | None:
    """A sentence for a body that cannot be read as a JSON object at all, else None.

    Such a request is malformed (400). A well-formed JSON object with invalid fields is 422.
    """
    for error in errors:
        loc, kind = tuple(error["loc"]), error["type"]
        if kind == "json_invalid":
            return "Request body is not valid JSON"
        if loc == ("body",) and kind == "missing":
            return "Request body is required"
        if loc == ("body",) and kind in _NOT_AN_OBJECT:
            return "Request body must be a JSON object sent with Content-Type: application/json"
    return None


@app.exception_handler(RequestValidationError)
async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    malformed = _malformed_body(exc.errors())
    if malformed:
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": malformed})
    # Built field by field: FastAPI's default response repeats the submitted values.
    errors = [{"field": _field_name(error), "message": _message(error)} for error in exc.errors()]
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        content={"detail": "Validation failed", "errors": errors})


@app.exception_handler(InvalidFieldError)
async def _invalid_field(_request: Request, exc: InvalidFieldError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        content={"detail": "Validation failed",
                                 "errors": [{"field": exc.field, "message": exc.message}]})


@app.exception_handler(NotFoundError)
async def _not_found(_request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": exc.message})


@app.exception_handler(ConflictError)
async def _conflict(_request: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": exc.message})


@app.exception_handler(IntegrityError)
async def _integrity_error(_request: Request, exc: IntegrityError) -> JSONResponse:
    # The database refused the data (a unique, foreign key or CHECK constraint). Services check
    # these rules first, so this is reached only by a race between requests. Class name only:
    # the driver message names the constraint and could include values.
    logger.warning("Database constraint refused a write: %s", type(exc.orig).__name__)
    return JSONResponse(status_code=status.HTTP_409_CONFLICT,
                        content={"detail": "The request conflicts with existing data"})


@app.exception_handler(SQLAlchemyError)
async def _database_error(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
    # Class name only: driver messages can include connection details and query values.
    logger.error("Database error: %s", type(exc).__name__)
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        content={"detail": "Service temporarily unavailable"})


@app.exception_handler(Exception)
async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, type(exc).__name__)
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        content={"detail": "Internal server error"})


# --- Service endpoints ---

@app.get("/", response_model=RootResponse, tags=["Service"], summary="Service information")
def root():
    return RootResponse(service=settings.app_name, version=settings.app_version, docs_url=app.docs_url)


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
