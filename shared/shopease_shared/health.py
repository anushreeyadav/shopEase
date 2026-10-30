"""Liveness (`GET /health`) and readiness (`GET /health/ready`) routes."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from shopease_shared.settings import BaseServiceSettings

logger = logging.getLogger("shopease.health")

# A readiness check returns normally when the dependency is usable and raises otherwise.
ReadinessCheck = Callable[[], Awaitable[None]]


class LivenessResponse(BaseModel):
    service: str
    status: str
    version: str
    environment: str


class ReadinessResponse(BaseModel):
    service: str
    status: str
    checks: dict[str, str]


def build_health_router(
    settings: BaseServiceSettings,
    checks: Mapping[str, ReadinessCheck] | None = None,
    check_timeout_seconds: float = 3.0,
) -> APIRouter:
    router = APIRouter(tags=["health"])
    checks = dict(checks or {})

    @router.get("/health", response_model=LivenessResponse, summary="Liveness check")
    async def liveness() -> LivenessResponse:
        """The process is up and serving requests. Does not touch dependencies."""
        return LivenessResponse(
            service=settings.service_name,
            status="ok",
            version=settings.version,
            environment=settings.environment,
        )

    @router.get(
        "/health/ready",
        response_model=ReadinessResponse,
        summary="Readiness check",
        responses={503: {"model": ReadinessResponse, "description": "A dependency is unavailable"}},
    )
    async def readiness() -> JSONResponse:
        """Checks the service's own dependencies. Returns 503 if any of them is unavailable."""

        async def run(name: str, check: ReadinessCheck) -> tuple[str, str]:
            try:
                await asyncio.wait_for(check(), timeout=check_timeout_seconds)
                return name, "ok"
            except Exception as exc:
                # Log the cause; the response only says "unavailable" (no hosts or errors leak).
                logger.warning("readiness check failed", extra={"check": name, "error": repr(exc)})
                return name, "unavailable"

        results = dict(await asyncio.gather(*(run(n, c) for n, c in checks.items())))
        ready = all(state == "ok" for state in results.values())
        body = ReadinessResponse(
            service=settings.service_name,
            status="ready" if ready else "not_ready",
            checks=results,
        )
        return JSONResponse(body.model_dump(), status_code=200 if ready else 503)

    return router
