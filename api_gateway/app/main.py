"""API Gateway entry point: the single client-facing entry point (port 8000).

Run from the repository root:
    uvicorn app.main:app --app-dir api_gateway --port 8000
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings, get_settings
from app.edge import AUTH_LIMITED, FixedWindowRateLimiter, is_public
from app.proxy import forward, resolve
from shopease_shared.openapi import configure_openapi
from shopease_shared import ShopEaseError, build_health_router, configure_logging, install_common
from shopease_shared.security import KeyProvider, TokenVerifier, bearer_token

logger = logging.getLogger(__name__)

PROXIED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def create_app(
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    key_provider: KeyProvider | None = None,
) -> FastAPI:
    """`transport` and `key_provider` let tests replace the network and the JWKS fetch."""
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level)
    verifier = TokenVerifier.from_settings(settings, key_provider)
    limiter = FixedWindowRateLimiter()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        timeout = httpx.Timeout(
            settings.upstream_timeout_seconds, connect=settings.upstream_connect_timeout_seconds
        )
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            app.state.http = client
            logger.info("gateway starting", extra={"environment": settings.environment})
            yield
        logger.info("gateway stopped")

    app = FastAPI(
        title="ShopEase API Gateway",
        version=settings.version,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings
    app.state.token_verifier = verifier

    # CORS is a public-edge concern, so only the gateway configures it, and only when
    # origins are listed. Added before install_common so the request-ID layer stays outermost.
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=PROXIED_METHODS,
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
            expose_headers=["X-Request-ID", "Location", "Retry-After"],
        )
    configure_openapi(
        app,
        description=(
            "The single client-facing entry point. It routes `/api/auth`, `/api/users`, `/api/products`, `/api/categories`, `/api/orders` and `/api/payments` to the owning services with paths unchanged, authenticates access tokens at the edge, rate-limits credential endpoints, and never routes `/internal/*`. The proxied routes are documented in each service's own Swagger UI; the route map and verified endpoint list are in `docs/api_gateway.md`."
            + '\n\nAll errors use the ShopEase envelope (`ErrorResponse`). Every response carries `X-Request-ID`. Public routes (`/api/...`) are reached through the API Gateway on port 8000 with the same paths; `/internal/...` routes are for other services only. Use **Authorize** with an access token from `POST /api/auth/login`. Contracts: `docs/rest_api_notes.md`.'
        ),
        tags=[
            {"name": "health", "description": "Gateway liveness and upstream readiness"},
        ],
    )
    install_common(app)

    def upstream_check(base_url: str) -> Callable[[], Awaitable[None]]:
        async def check() -> None:
            response = await app.state.http.get(base_url.rstrip("/") + "/health", timeout=2.0)
            response.raise_for_status()

        return check

    services = {u.service: u.base_url for u in settings.upstreams}
    app.include_router(
        build_health_router(settings, {name: upstream_check(url) for name, url in services.items()})
    )

    @app.api_route("/api/{path:path}", methods=PROXIED_METHODS, include_in_schema=False)
    async def proxy(request: Request) -> Response:
        path, method = request.url.path, request.method
        upstream = resolve(path, settings.upstreams)
        if upstream is None:
            raise StarletteHTTPException(status_code=404)

        # 1. Rate limit per client IP (proxy headers are not trusted for the client address).
        limit, group = settings.rate_limit_default_per_minute, "default"
        if method == "POST" and AUTH_LIMITED.match(path):
            limit, group = settings.rate_limit_auth_per_minute, "auth"
        decision = None
        if limit:
            client = request.client.host if request.client else "unknown"
            decision = limiter.hit(f"{group}:{client}", limit)
            if not decision.allowed:
                raise ShopEaseError(
                    429,
                    "RATE_LIMITED",
                    f"Too many requests. Retry after {decision.reset_seconds} seconds.",
                    headers={"Retry-After": str(decision.reset_seconds)},
                )

        # 2. Edge authentication: protected routes need a genuine, unexpired access token.
        if not is_public(method, path):
            await run_in_threadpool(verifier.verify, bearer_token(request), "access")

        # 3. Body size limit (checked on the declared length and on what actually arrived).
        too_large = ShopEaseError(413, "PAYLOAD_TOO_LARGE", "The request body is too large.")
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > settings.max_request_body_bytes:
            raise too_large
        body = await request.body()
        if len(body) > settings.max_request_body_bytes:
            raise too_large

        response = await forward(request, app.state.http, upstream, body)
        if decision is not None:
            response.headers["RateLimit-Limit"] = str(decision.limit)
            response.headers["RateLimit-Remaining"] = str(decision.remaining)
            response.headers["RateLimit-Reset"] = str(decision.reset_seconds)
        return response

    return app


app = create_app()
