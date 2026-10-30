"""Gateway edge controls: authentication before proxying, rate limits, header hygiene."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.edge import FixedWindowRateLimiter, is_public
from app.main import create_app
from tests.jwt_helpers import KEY_PROVIDER, OTHER_KEY, bearer, make_token


def make_client(seen: list, **overrides) -> TestClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    settings = Settings(_env_file=None, APP_ENV="test", **overrides)
    app = create_app(settings, transport=httpx.MockTransport(handler), key_provider=KEY_PROVIDER)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    "method,path,public",
    [
        ("POST", "/api/auth/login", True),
        ("POST", "/api/auth/register", True),
        ("GET", "/api/auth/.well-known/jwks.json", True),
        ("GET", "/api/products", True),
        ("GET", "/api/products/9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c61", True),
        ("GET", "/api/categories", True),
        ("GET", "/api/categories/c1a2b3c4-d5e6-4f70-8a91-b2c3d4e5f601", True),
        ("POST", "/api/categories", False),
        ("PATCH", "/api/products/x/inventory", False),
        ("POST", "/api/payments/webhooks/mock", True),
        ("POST", "/api/products", False),
        ("POST", "/api/auth/logout", False),
        ("GET", "/api/users/me", False),
        ("GET", "/api/orders", False),
        ("GET", "/api/products/x/inventory", False),
    ],
)
def test_public_route_table(method, path, public):
    assert is_public(method, path) is public


@pytest.mark.parametrize(
    "headers,code",
    [
        ({}, "UNAUTHENTICATED"),
        (bearer("garbage"), "INVALID_TOKEN"),
        (bearer(make_token(expires_in=-120)), "TOKEN_EXPIRED"),
        (bearer(make_token(key=OTHER_KEY)), "INVALID_TOKEN"),
        (bearer(make_token("svc:order", token_use="service", scope="orders:read")), "INVALID_TOKEN"),
    ],
    ids=["missing", "garbage", "expired", "wrong-key", "service-token"],
)
def test_protected_routes_are_rejected_before_reaching_a_service(headers, code):
    seen: list = []
    with make_client(seen) as client:
        response = client.get("/api/users/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == code
    assert seen == []


def test_public_and_authenticated_requests_are_forwarded():
    seen: list = []
    with make_client(seen) as client:
        assert client.get("/api/products").status_code == 200
        assert client.post("/api/auth/login", json={}).status_code == 200
        assert client.get("/api/users/me", headers=bearer(make_token())).status_code == 200
    assert len(seen) == 3


def test_client_supplied_user_token_header_is_stripped():
    seen: list = []
    with make_client(seen) as client:
        client.get("/api/users/me", headers={**bearer(make_token()), "X-User-Token": make_token()})
    assert "x-user-token" not in seen[0].headers


def test_credential_endpoints_are_rate_limited_per_client():
    seen: list = []
    with make_client(seen, RATE_LIMIT_AUTH_PER_MINUTE=3) as client:
        statuses = [client.post("/api/auth/login", json={}).status_code for _ in range(4)]
        assert client.get("/api/products").status_code == 200  # other routes: default limit is off
        limited = client.post("/api/auth/register", json={})
    assert statuses == [200, 200, 200, 429]
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert int(limited.headers["Retry-After"]) > 0
    assert len(seen) == 4  # 3 logins + 1 product request; limited requests never left the gateway


def test_rate_limit_headers_and_default_limit():
    seen: list = []
    with make_client(seen, RATE_LIMIT_DEFAULT_PER_MINUTE=2) as client:
        first = client.get("/api/products")
        client.get("/api/products")
        third = client.get("/api/products")
    assert first.headers["RateLimit-Limit"] == "2" and first.headers["RateLimit-Remaining"] == "1"
    assert third.status_code == 429


def test_rate_limits_can_be_disabled():
    seen: list = []
    with make_client(seen, RATE_LIMIT_AUTH_PER_MINUTE=0) as client:
        assert all(client.post("/api/auth/login", json={}).status_code == 200 for _ in range(30))


def test_fixed_window_resets_after_the_window():
    now = [0.0]
    limiter = FixedWindowRateLimiter(window_seconds=60, clock=lambda: now[0])
    assert [limiter.hit("k", 2).allowed for _ in range(3)] == [True, True, False]
    assert limiter.hit("other", 2).allowed  # keys are independent
    now[0] = 61.0
    assert limiter.hit("k", 2).allowed
