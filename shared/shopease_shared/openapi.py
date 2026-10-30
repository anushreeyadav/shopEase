"""OpenAPI (Swagger UI) documentation that matches how ShopEase services actually behave.

FastAPI documents `422` with its own `HTTPValidationError` body and knows nothing about our
token dependencies. This module post-processes each service's schema so that:
- every error response refers to the real ShopEase envelope (`ErrorResponse`, §1.8);
- operations protected by a user token, an optional token or a service token declare the
  matching security scheme (Swagger UI then shows the "Authorize" padlock);
- admin/scope-protected operations also document `403`, token-protected ones `401`.
"""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, TypeAdapter

from shopease_shared import security


class ErrorDetail(BaseModel):
    field: str = Field(examples=["body.items[0].quantity"])
    issue: str = Field(examples=["exceeds available stock (2)"])


class ErrorBody(BaseModel):
    code: str = Field(description="Stable, machine-readable code", examples=["OUT_OF_STOCK"])
    message: str = Field(description="Human-readable; never contains internals", examples=["Not enough stock."])
    details: list[ErrorDetail] | None = Field(default=None, description="Per-field problems, when relevant")
    request_id: str | None = Field(description="Correlation ID, also in the X-Request-ID header",
                                   examples=["req-7f3a9c2e"])


class ErrorResponse(BaseModel):
    """Every error produced by ShopEase uses this envelope (docs/rest_api_notes.md §1.8)."""

    error: ErrorBody


_ERROR_REF = {"$ref": "#/components/schemas/ErrorResponse"}
_SECURITY_SCHEMES = {
    "bearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "User access token from POST /api/auth/login (`Authorization: Bearer <token>`).",
    },
    "serviceToken": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "Internal service token from POST /internal/auth/service-token (client credentials). "
                       "Internal routes are never reachable through the gateway.",
    },
}


def _dependency_calls(dependant) -> set[str]:
    names: set[str] = set()
    for dep in dependant.dependencies:
        if dep.call is not None:
            names.add(getattr(dep.call, "__qualname__", getattr(dep.call, "__name__", "")))
        names |= _dependency_calls(dep)
    return names


def _auth_kind(route: APIRoute) -> tuple[str | None, bool]:
    """(security scheme or None, whether a role/scope check can answer 403)."""
    calls = _dependency_calls(route.dependant)
    forbidden = any(c.startswith(("require_admin", "require_scope")) for c in calls)
    if security.current_service.__qualname__ in calls:
        return "serviceToken", forbidden
    if security.current_user.__qualname__ in calls and security.optional_user.__qualname__ not in calls:
        return "bearerAuth", forbidden
    if security.optional_user.__qualname__ in calls:
        return "optional", forbidden
    return None, forbidden


def _api_routes(routes):
    """APIRoutes, also inside included routers (FastAPI wraps them in `_IncludedRouter`)."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        nested = getattr(route, "original_router", None) or getattr(route, "router", None)
        if nested is not None and hasattr(nested, "routes"):
            yield from _api_routes(nested.routes)


def _error(description: str) -> dict[str, Any]:
    return {"description": description, "content": {"application/json": {"schema": _ERROR_REF}}}


def configure_openapi(app: FastAPI, description: str, tags: list[dict[str, str]] | None = None) -> None:
    app.description = description
    app.openapi_tags = tags

    def build() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, description=app.description,
                             routes=app.routes, tags=app.openapi_tags)
        components = schema.setdefault("components", {})
        error_schema = TypeAdapter(ErrorResponse).json_schema(ref_template="#/components/schemas/{model}")
        schemas = components.setdefault("schemas", {})
        schemas.update(error_schema.pop("$defs", {}))
        schemas["ErrorResponse"] = error_schema
        components["securitySchemes"] = _SECURITY_SCHEMES

        for route in _api_routes(app.routes):
            if not route.include_in_schema:
                continue
            kind, forbidden = _auth_kind(route)
            for method in route.methods:
                operation = schema["paths"].get(route.path_format, {}).get(method.lower())
                if operation is None:
                    continue
                responses = operation.setdefault("responses", {})
                if "422" in responses:
                    responses["422"] = _error("Validation failed (input values are never echoed)")
                if kind == "bearerAuth":
                    operation["security"] = [{"bearerAuth": []}]
                elif kind == "serviceToken":
                    operation["security"] = [{"serviceToken": []}]
                elif kind == "optional":
                    operation["security"] = [{}, {"bearerAuth": []}]
                if kind in ("bearerAuth", "serviceToken", "optional"):
                    responses.setdefault("401", _error("Missing, invalid or expired token"))
                if forbidden:
                    responses.setdefault("403", _error("Authenticated, but the role or scope does not allow this"))
                for code, response in responses.items():
                    if code[0] in "45" and "content" not in response:
                        response["content"] = {"application/json": {"schema": _ERROR_REF}}
                responses.setdefault("default", _error("Any other error, in the standard ShopEase envelope"))

        # FastAPI's own validation schemas are no longer referenced.
        for unused in ("HTTPValidationError", "ValidationError"):
            schemas.pop(unused, None)
        app.openapi_schema = schema
        return schema

    app.openapi = build
