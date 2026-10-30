"""Proxy behaviour: what passes through unchanged, what the gateway hides, how failures map."""

import io
import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from shopease_shared.log_config import JsonFormatter
from tests.jwt_helpers import KEY_PROVIDER, bearer, make_token

TOKEN = make_token()
AUTH = bearer(TOKEN)


def client_for(handler, **overrides) -> TestClient:
    settings = Settings(_env_file=None, APP_ENV="test", RATE_LIMIT_AUTH_PER_MINUTE=0, **overrides)
    app = create_app(settings, transport=httpx.MockTransport(handler), key_provider=KEY_PROVIDER)
    return TestClient(app, raise_server_exceptions=False)


def recorder(response: httpx.Response | None = None):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response if response is not None else httpx.Response(200, json={"ok": True})

    return seen, handler


# --- Pass-through ------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_method_path_query_body_and_headers_are_preserved(method):
    seen, handler = recorder()
    body = json.dumps({"line1": "12 Example St"}).encode() if method in ("POST", "PUT", "PATCH") else b""
    with client_for(handler) as client:
        client.request(
            method,
            "/api/users/me/addresses?limit=5&offset=10&q=a%20b",
            content=body,
            headers={**AUTH, "Content-Type": "application/json", "Accept": "application/json",
                     "Idempotency-Key": "key-123456", "Accept-Language": "en-IN"},
        )
    [upstream] = seen
    assert upstream.method == method
    assert upstream.url.path == "/api/users/me/addresses"
    assert upstream.url.query == b"limit=5&offset=10&q=a%20b"
    assert upstream.content == body
    for name, value in [("authorization", f"Bearer {TOKEN}"), ("content-type", "application/json"),
                        ("accept", "application/json"), ("idempotency-key", "key-123456"),
                        ("accept-language", "en-IN")]:
        assert upstream.headers[name] == value
    assert upstream.headers["x-request-id"].startswith("req-")
    assert upstream.headers["x-forwarded-for"] == "testclient"


@pytest.mark.parametrize(
    "status,body",
    [
        (200, {"ok": True}), (201, {"id": 1}), (202, {"status": "PROCESSING"}), (204, None),
        (400, {"error": {"code": "BAD_REQUEST"}}), (401, {"error": {"code": "INVALID_TOKEN"}}),
        (403, {"error": {"code": "FORBIDDEN"}}), (404, {"error": {"code": "ORDER_NOT_FOUND"}}),
        (409, {"error": {"code": "OUT_OF_STOCK"}}), (422, {"error": {"code": "VALIDATION_ERROR"}}),
        (423, {"error": {"code": "ACCOUNT_LOCKED"}}), (429, {"error": {"code": "RATE_LIMITED"}}),
        (500, {"error": {"code": "INTERNAL_ERROR"}}), (501, {"error": {"code": "WEBHOOKS_NOT_SUPPORTED"}}),
        (503, {"error": {"code": "DEPENDENCY_UNAVAILABLE"}}), (504, {"error": {"code": "DEPENDENCY_TIMEOUT"}}),
    ],
)
def test_upstream_status_codes_and_bodies_pass_through(status, body):
    upstream = httpx.Response(status, json=body, headers={"Retry-After": "3", "Location": "/api/orders/1"}) \
        if body is not None else httpx.Response(status)
    _, handler = recorder(upstream)
    with client_for(handler) as client:
        response = client.post("/api/orders", headers=AUTH, json={})
    assert response.status_code == status
    if body is not None:
        assert response.json() == body
        assert response.headers["Retry-After"] == "3" and response.headers["Location"] == "/api/orders/1"
    else:
        assert response.content == b""


def test_identity_and_forwarding_headers_from_clients_are_removed():
    seen, handler = recorder()
    spoofed = {
        "X-User-Token": make_token(), "X-User-Id": "someone", "X-User-Role": "admin",
        "X-Internal-Service": "svc:order", "X-Service-Token": "x", "X-Forwarded-For": "10.0.0.1",
        "X-Forwarded-Host": "evil.example", "X-Forwarded-Proto": "https", "Forwarded": "for=10.0.0.1",
        "X-Real-IP": "10.0.0.1",
    }
    with client_for(handler) as client:
        client.get("/api/users/me", headers={**AUTH, **spoofed})
    headers = seen[0].headers
    for name in ("x-user-token", "x-user-id", "x-user-role", "x-internal-service", "x-service-token",
                 "x-forwarded-host", "forwarded", "x-real-ip"):
        assert name not in headers, name
    assert headers["x-forwarded-for"] == "testclient"  # set from the TCP peer, not the client's claim
    assert headers["x-forwarded-proto"] == "http"


def test_client_request_id_is_kept_when_safe():
    seen, handler = recorder()
    with client_for(handler) as client:
        response = client.get("/api/products", headers={"X-Request-ID": "req-from-client"})
    assert seen[0].headers["x-request-id"] == "req-from-client" == response.headers["X-Request-ID"]


# --- What the gateway hides ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "upstream",
    [
        httpx.Response(500, text="Traceback (most recent call last):\n  File \"/srv/app/db.py\", password=..."),
        httpx.Response(502, text="<html>nginx bad gateway at 10.0.3.7</html>", headers={"Content-Type": "text/html"}),
        httpx.Response(503, json={"detail": "upstream connect error to http://order_service:8004"}),
        httpx.Response(200, content=b'{"truncated": ', headers={"Content-Type": "application/json"}),
        httpx.Response(600, json={"ok": True}),
        httpx.Response(199, json={"ok": True}),
    ],
    ids=["traceback-500", "html-502", "non-envelope-503", "malformed-json", "status-600", "status-199"],
)
def test_malformed_or_leaky_upstream_responses_become_gateway_errors(upstream):
    _, handler = recorder(upstream)
    with client_for(handler) as client:
        response = client.get("/api/orders", headers=AUTH)
    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "BAD_UPSTREAM_RESPONSE"
    assert error["message"] == "The order service returned an invalid response."
    for secret in ("Traceback", "password", "10.0.3.7", "order_service:8004", "truncated"):
        assert secret not in response.text


def test_internal_locations_and_server_headers_are_rewritten_or_dropped():
    upstream = httpx.Response(
        201, json={"order_id": "o1"},
        headers={"Location": "http://localhost:8004/api/orders/o1", "Server": "uvicorn", "X-Powered-By": "x"},
    )
    _, handler = recorder(upstream)
    with client_for(handler) as client:
        response = client.post("/api/orders", headers=AUTH, json={})
    assert response.headers["Location"] == "/api/orders/o1"
    assert response.headers.get("server") != "uvicorn"
    assert "x-powered-by" not in response.headers


# --- Failures and timeouts ---------------------------------------------------------------------------


def test_missing_service_gives_503_without_internal_details():
    def handler(request):
        raise httpx.ConnectError("[Errno 111] Connection refused to order_service:8004", request=request)

    with client_for(handler, ORDER_SERVICE_URL="http://order_service:8004") as client:
        response = client.get("/api/orders", headers=AUTH)
    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "SERVICE_UNAVAILABLE",
        "message": "The order service is temporarily unavailable.",
        "request_id": response.headers["X-Request-ID"],
    }
    assert "8004" not in response.text and "Errno" not in response.text
    assert response.headers["Retry-After"] == "2"


def test_only_safe_methods_are_retried_and_only_when_the_request_never_arrived():
    calls = {"n": 0}

    def flaky(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"ok": True})

    with client_for(flaky) as client:
        assert client.get("/api/products").status_code == 200
    assert calls["n"] == 2

    calls["n"] = 0
    with client_for(flaky) as client:
        assert client.post("/api/orders", headers=AUTH, json={}).status_code == 503
    assert calls["n"] == 1  # a write is never re-sent

    def slow(request):
        calls["n"] += 1
        raise httpx.ReadTimeout("slow", request=request)

    calls["n"] = 0
    with client_for(slow) as client:
        response = client.get("/api/products")
    assert response.status_code == 504 and response.json()["error"]["code"] == "UPSTREAM_TIMEOUT"
    assert calls["n"] == 1  # a timeout may have been processed: no retry


@pytest.mark.parametrize(
    "path,expected",
    [("/api/auth/login", 5.0), ("/api/users/me", 5.0), ("/api/products", 5.0),
     ("/api/orders", 10.0), ("/api/payments", 20.0)],
)
def test_each_route_uses_its_own_timeout(path, expected):
    seen, handler = recorder()
    with client_for(handler) as client:
        client.post(path, headers=AUTH, json={})
    timeouts = seen[0].extensions["timeout"]
    assert timeouts["read"] == expected and timeouts["connect"] == 1.0


def test_oversized_bodies_are_refused_before_reaching_a_service():
    seen, handler = recorder()
    with client_for(handler, MAX_REQUEST_BODY_BYTES=2048) as client:
        big = client.post("/api/orders", headers={**AUTH, "Content-Type": "application/json"}, content=b"x" * 4096)
        ok = client.post("/api/orders", headers=AUTH, json={"items": []})
    assert big.status_code == 413 and big.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert ok.status_code == 200 and len(seen) == 1


def test_upstream_calls_are_logged_without_urls_queries_or_tokens():
    seen, handler = recorder()
    buffer = io.StringIO()
    log_handler = logging.StreamHandler(buffer)
    log_handler.setFormatter(JsonFormatter("api_gateway"))
    with client_for(handler) as client:
        logging.getLogger().addHandler(log_handler)
        try:
            client.get("/api/users/me/addresses?secret_query=abc", headers=AUTH)
        finally:
            logging.getLogger().removeHandler(log_handler)
    lines = [json.loads(line) for line in buffer.getvalue().splitlines()]
    upstream_line = next(line for line in lines if line["message"] == "upstream call")
    assert upstream_line["upstream"] == "user_service" and upstream_line["outcome"] == 200
    text = buffer.getvalue()
    assert TOKEN not in text and "secret_query" not in text and "localhost:8002" not in text
