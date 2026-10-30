"""The ShopEase error envelope (rest_api_notes.md §1.8) and the handlers that produce it."""

import logging
from http import HTTPStatus
from typing import Any, NoReturn

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from shopease_shared.request_id import REQUEST_ID_HEADER

logger = logging.getLogger("shopease.errors")

# Default machine-readable codes for errors raised as plain HTTPException (or by Starlette).
_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    501: "NOT_IMPLEMENTED",
    502: "BAD_UPSTREAM_RESPONSE",
    503: "SERVICE_UNAVAILABLE",
    504: "UPSTREAM_TIMEOUT",
}


class ShopEaseError(Exception):
    """Raise from any endpoint to return the standard error envelope."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def not_implemented() -> NoReturn:
    """Placeholder body for routes that are planned in the API contract but not built yet."""
    raise ShopEaseError(501, "NOT_IMPLEMENTED", "This endpoint is planned but not implemented yet.")


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id}
    if details:
        body["details"] = details
    response_headers = dict(headers or {})
    if request_id:
        response_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse({"error": body}, status_code=status_code, headers=response_headers)


async def _shopease_error(request: Request, exc: ShopEaseError) -> JSONResponse:
    return error_response(request, exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _STATUS_CODES.get(exc.status_code, "ERROR")
    if exc.status_code == 404:
        message = f"No route for {request.method} {request.url.path}."
        code = "ROUTE_NOT_FOUND"
    elif isinstance(exc.detail, str):
        message = exc.detail
    else:
        message = HTTPStatus(exc.status_code).phrase
    return error_response(request, exc.status_code, code, message, headers=exc.headers)


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # OPEN-14 proposal: keep 422 but use the envelope, and never echo raw input
    # (FastAPI's default `input` field would repeat passwords back to the client).
    details = [
        {"field": ".".join(str(part) for part in err.get("loc", ())), "issue": err.get("msg", "")}
        for err in exc.errors()
    ]
    return error_response(request, 422, "VALIDATION_ERROR", "Request validation failed.", details)


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    # Full details go to the logs only; the client gets a generic message. This handler runs
    # outside RequestIDMiddleware, so the request ID is passed explicitly.
    logger.error(
        "unhandled exception",
        exc_info=exc,
        extra={"request_id": getattr(request.state, "request_id", None)},
    )
    return error_response(request, 500, "INTERNAL_ERROR", "An unexpected error occurred.")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ShopEaseError, _shopease_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled_error)
