"""Exception handlers, so that every error response has the same JSON shape and leaks nothing."""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def _field_name(error: dict) -> str:
    if error["type"] == "json_invalid":
        return "body"
    # loc is ("body", "field", ...); a model-level error has only ("body",).
    return ".".join(str(part) for part in error["loc"][1:]) or str(error["loc"][0])


async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    # Built field by field, in the Authentication Service's format. FastAPI's default response
    # repeats the submitted values, such as phone numbers and dates of birth.
    errors = [
        {"field": _field_name(error), "message": error["msg"].removeprefix("Value error, ")}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": "Validation failed", "errors": errors},
    )


async def _database_error(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
    # get_db() has already rolled the session back by the time this response is sent.
    # Class name only: driver messages can include connection details and query values.
    logger.error("Database error: %s", type(exc).__name__)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Service temporarily unavailable"},
    )


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Without this, Starlette answers with a plain-text 500. The message and traceback can hold
    # internal details, so only the class name and route are logged, and nothing is returned.
    logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, type(exc).__name__)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(SQLAlchemyError, _database_error)
    app.add_exception_handler(Exception, _unexpected_error)
