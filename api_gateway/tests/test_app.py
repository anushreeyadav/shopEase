"""In-process gateway tests. The network is replaced with httpx.MockTransport."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.jwt_helpers import KEY_PROVIDER, bearer, make_token

TOKEN = make_token()


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, APP_ENV="test", **overrides)


def make_client(handler, **overrides) -> TestClient:
    app = create_app(
        make_settings(**overrides), transport=httpx.MockTransport(handler), key_provider=KEY_PROVIDER
    )
    return TestClient(app, raise_server_exceptions=False)


def ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"status": "ok"})


def test_liveness():
    with make_client(ok_handler) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "api_gateway"
    assert response.json()["status"] == "ok"


def test_readiness_ok_when_all_upstreams_healthy():
    with make_client(ok_handler) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    checks = response.json()["checks"]
    assert set(checks) == {
        "auth_service",
        "user_service",
        "product_service",
        "order_service",
        "payment_service",
    }
    assert set(checks.values()) == {"ok"}


def test_readiness_503_when_an_upstream_is_down():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.port == 8004:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"status": "ok"})

    with make_client(handler) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["order_service"] == "unavailable"


@pytest.mark.parametrize(
    "path,port",
    [
        ("/api/auth/login", 8001),
        ("/api/users/me", 8002),
        ("/api/products?limit=5&offset=0", 8003),
        ("/api/categories", 8003),
        ("/api/orders", 8004),
        ("/api/payments/webhooks/mock", 8005),
    ],
)
def test_routes_to_owning_service_with_path_unchanged(path, port):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(501, json={"error": {"code": "NOT_IMPLEMENTED"}})

    with make_client(handler) as client:
        response = client.post(path, headers={"X-Request-ID": "req-gw-1", **bearer(TOKEN)})

    assert response.status_code == 501
    assert response.headers["X-Request-ID"] == "req-gw-1"
    [upstream] = seen
    assert upstream.url.port == port
    assert upstream.url.raw_path.decode() == path
    assert upstream.headers["X-Request-ID"] == "req-gw-1"
    assert upstream.headers["Authorization"] == f"Bearer {TOKEN}"
    assert upstream.headers["host"] == f"localhost:{port}"


@pytest.mark.parametrize("path", ["/internal/orders/x/payable", "/api/unknown", "/api/authx"])
def test_internal_and_unknown_paths_are_not_routed(path):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    with make_client(handler) as client:
        response = client.get(path)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ROUTE_NOT_FOUND"
    assert seen == []


@pytest.mark.parametrize(
    "exc,status,code",
    [
        (httpx.ConnectError, 503, "SERVICE_UNAVAILABLE"),
        (httpx.ReadTimeout, 504, "UPSTREAM_TIMEOUT"),
        (httpx.RemoteProtocolError, 502, "BAD_UPSTREAM_RESPONSE"),
    ],
)
def test_upstream_failures_map_to_error_envelope(exc, status, code):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc("boom", request=request)

    with make_client(handler) as client:
        response = client.get("/api/orders", headers=bearer(TOKEN))
    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    assert "boom" not in response.text
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_cors_disabled_by_default():
    with make_client(ok_handler) as client:
        response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert "access-control-allow-origin" not in response.headers


def test_cors_allows_only_configured_origins():
    with make_client(ok_handler, CORS_ALLOWED_ORIGINS="http://localhost:3000") as client:
        allowed = client.options(
            "/api/products",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
        )
        denied = client.options(
            "/api/products",
            headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
        )
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in denied.headers


def test_openapi_and_docs_load():
    with make_client(ok_handler) as client:
        assert client.get("/docs").status_code == 200
        paths = client.get("/openapi.json").json()["paths"]
    assert set(paths) == {"/health", "/health/ready"}
