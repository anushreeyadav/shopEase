"""Access rules, and token verification against a stand-in Authentication Service."""

import base64
import json
import time

import httpx
import pytest
from fastapi import HTTPException
from jose import jwt

from app.core.security import get_auth_client, has_expected_format, verify_access_token
from app.main import app

VERIFY_URL = "http://auth.test/api/auth/verify-token"
# Test-only key. This service never verifies signatures, so any key produces a token it will forward.
_TEST_KEY = "test-only-key-not-used-by-any-service-0123456789"


def make_token(user_id: int = 7, role: str = "USER", *, alg: str = "HS256") -> str:
    """A token shaped like the Authentication Service's: claims sub, role, iat, exp."""
    now = int(time.time())
    return jwt.encode({"sub": str(user_id), "role": role, "iat": now, "exp": now + 1800}, _TEST_KEY, algorithm=alg)


TOKEN = make_token()


def _user(role="USER", is_active=True, **extra):
    return {"valid": True, "user": {"id": 7, "full_name": "Asha", "email": "a@example.com",
                                    "role": role, "is_active": is_active, **extra}}


def _client(status_code: int, body=None, *, raise_error: Exception | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if raise_error:
            raise raise_error
        assert str(request.url) == VERIFY_URL
        return httpx.Response(status_code, json=body)
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- Access rules (caller switched with auth_as) ---

ADMIN_ONLY = [
    ("post", "/api/categories", {"name": "X"}),
    ("patch", "/api/categories/1", {"name": "X"}),
    ("delete", "/api/categories/1", None),
    ("post", "/api/products", {"sku": "A", "name": "A", "price": "1", "category_id": 1}),
    ("patch", "/api/products/1", {"name": "X"}),
    ("delete", "/api/products/1", None),
    ("get", "/api/inventory/1", None),
    ("get", "/api/inventory/low-stock", None),
    ("get", "/api/inventory/1/history", None),
    ("post", "/api/inventory/1/stock-in", {"quantity": 1}),
    ("post", "/api/inventory/1/stock-out", {"quantity": 1}),
]


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ONLY)
def test_admin_routes_reject_anonymous_and_customers(client, auth_as, method, path, body):
    kwargs = {"json": body} if body is not None else {}

    auth_as(None)
    response = client.request(method, path, **kwargs)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"

    auth_as(7, role="USER")
    response = client.request(method, path, **kwargs)
    assert response.status_code == 403
    assert response.json() == {"detail": "Admin role required"}


def test_browsing_is_public(client, auth_as, make_product, category):
    product = make_product()
    auth_as(None)
    assert client.get("/api/categories").status_code == 200
    assert client.get(f"/api/categories/{category['id']}").status_code == 200
    assert client.get("/api/products").status_code == 200
    assert client.get(f"/api/products/{product['id']}").status_code == 200


@pytest.mark.parametrize("path", ["/api/categories", "/api/products", "/api/products/1", "/api/categories/1"])
def test_include_inactive_needs_admin(client, auth_as, path):
    auth_as(None)
    assert client.get(path, params={"include_inactive": True}).status_code == 401
    auth_as(7, role="USER")
    assert client.get(path, params={"include_inactive": True}).status_code == 403


# --- Token verification through the Authentication Service ---

def test_valid_token_is_accepted():
    user = verify_access_token(TOKEN, _client(200, _user(role="ADMIN")))
    assert (user.auth_user_id, user.role, user.is_admin) == (7, "ADMIN", True)


@pytest.mark.parametrize(("status_code", "body", "expected"), [
    (401, {"detail": "Could not validate credentials"}, 401),
    (403, {"detail": "Inactive user"}, 403),
    (500, {"detail": "boom"}, 503),
    (404, {"detail": "Not Found"}, 503),
    (200, {"valid": True}, 503),                    # malformed body
    (200, _user() | {"valid": False}, 401),         # never sent with 200; fail closed
    (200, _user(is_active=False), 403),
    (200, _user(id=True), 503),                     # boolean is not a user id
])
def test_verification_fails_closed(status_code, body, expected):
    with pytest.raises(HTTPException) as caught:
        verify_access_token(TOKEN, _client(status_code, body))
    assert caught.value.status_code == expected


def test_auth_service_down_is_503():
    with pytest.raises(HTTPException) as caught:
        verify_access_token(TOKEN, _client(0, raise_error=httpx.ConnectError("down")))
    assert caught.value.status_code == 503


def test_oversized_token_is_rejected_without_a_request():
    def handler(_request):
        raise AssertionError("must not be called")
    with pytest.raises(HTTPException) as caught:
        verify_access_token("x" * 5000, httpx.Client(transport=httpx.MockTransport(handler)))
    assert caught.value.status_code == 401


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


@pytest.mark.parametrize("token", [
    "not-a-jwt",
    "a.b",
    "a.b.c",
    make_token(alg="HS512"),                                          # not the configured algorithm
    f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64({'sub': '1', 'role': 'ADMIN'})}.",  # unsigned
    f"{_b64({'typ': 'JWT'})}.{_b64({'sub': '1'})}.c2ln",              # no alg at all
])
def test_malformed_tokens_are_rejected_without_a_request(token):
    def handler(_request):
        raise AssertionError("must not be called")
    assert has_expected_format(token) is False
    with pytest.raises(HTTPException) as caught:
        verify_access_token(token, httpx.Client(transport=httpx.MockTransport(handler)))
    assert caught.value.status_code == 401


def test_precheck_never_accepts_on_its_own():
    """A well-formed token still goes to the Authentication Service, which has the final say."""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, json={"detail": "Could not validate credentials"})

    assert has_expected_format(make_token(role="ADMIN")) is True
    with pytest.raises(HTTPException) as caught:
        verify_access_token(make_token(role="ADMIN"), httpx.Client(transport=httpx.MockTransport(handler)))
    assert caught.value.status_code == 401
    assert len(calls) == 1


def test_bearer_token_end_to_end(db_session, category):
    """No dependency overrides for auth: the real header is sent to the stand-in service."""
    from app.database.connection import get_db
    from fastapi.testclient import TestClient

    admin_token, user_token, unknown_token = make_token(1, "ADMIN"), make_token(7, "USER"), make_token(99)
    tokens = {admin_token: _user(role="ADMIN"), user_token: _user(role="USER")}

    def handler(request: httpx.Request) -> httpx.Response:
        token = request.headers["Authorization"].removeprefix("Bearer ")
        if token in tokens:
            return httpx.Response(200, json=tokens[token])
        return httpx.Response(401, json={"detail": "Could not validate credentials"})

    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_auth_client] = lambda: httpx.Client(transport=httpx.MockTransport(handler))
    client = TestClient(app)
    body = {"name": "Bags"}

    def bearer(token):
        return {"Authorization": f"Bearer {token}"}

    assert client.post("/api/categories", json=body, headers=bearer("bad")).status_code == 401
    assert client.post("/api/categories", json=body, headers=bearer(unknown_token)).status_code == 401
    assert client.post("/api/categories", json=body, headers=bearer(user_token)).status_code == 403
    assert client.post("/api/categories", json=body, headers=bearer(admin_token)).status_code == 201
    # A bad token on a public route is rejected, not silently treated as anonymous.
    assert client.get("/api/products", headers={"Authorization": "Bearer bad"}).status_code == 401
    assert client.get("/api/products").status_code == 200


def test_errors_do_not_echo_input(client):
    secret = "My Secret Value 123"
    response = client.post("/api/products", json={"sku": secret, "name": "x", "price": "1", "category_id": 1})
    assert response.status_code == 422
    assert secret not in response.text
