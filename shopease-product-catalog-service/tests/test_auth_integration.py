"""JWT integration with the ShopEase Authentication Service, end to end over HTTP.

No authentication dependency is overridden here. Requests carry real Authorization headers,
and the Catalog Service sends each token to a stand-in for POST /api/auth/verify-token.
The stand-in copies the logic of shopease-auth-service (app/core/security.py:
decode_access_token and get_current_user):

  - HS256 signature with its secret, which the Catalog Service never sees
  - required claims sub, iat and exp; exp must be in the future
  - sub must be a whole number and role a non-empty string
  - the user is loaded from its "database": unknown -> 401, inactive -> 403
  - 200 returns {"valid": true, "user": {...}} with the role from the database, not the token

Roles are the Authentication Service's own values: "ADMIN" and "USER" (its customer role).
"""

import base64
import json
import logging
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from jose import ExpiredSignatureError, JWTError, jwt

from app.core.security import ADMIN_ROLE, CUSTOMER_ROLE, get_auth_client, require_roles
from app.database.connection import get_db
from app.main import app

AUTH_SECRET = "stand-in-auth-secret-for-tests-only-0123456789abcdef"
UNAUTHORIZED = {"detail": "Could not validate credentials"}

ADMIN_ID, CUSTOMER_ID, INACTIVE_ID, DEMOTED_ID, LOWERCASE_ADMIN_ID = 1, 2, 3, 4, 5


class StandInAuthService:
    """Behaves like shopease-auth-service's verify-token endpoint."""

    def __init__(self) -> None:
        self.users = {
            ADMIN_ID: {"role": ADMIN_ROLE, "is_active": True},
            CUSTOMER_ID: {"role": CUSTOMER_ROLE, "is_active": True},
            INACTIVE_ID: {"role": ADMIN_ROLE, "is_active": False},
            DEMOTED_ID: {"role": CUSTOMER_ROLE, "is_active": True},  # role changed after login
            LOWERCASE_ADMIN_ID: {"role": "admin", "is_active": True},
        }
        self.calls = 0
        self.rejections: list[str] = []  # why each 401 was given, for assertions

    def issue(self, user_id: int, role: str | None = None, *, lifetime: int = 1800,
              secret: str = AUTH_SECRET) -> str:
        """Like the real create_access_token: claims sub, role, iat, exp."""
        now = int(time.time())
        role = role if role is not None else self.users[user_id]["role"]
        return jwt.encode({"sub": str(user_id), "role": role, "iat": now, "exp": now + lifetime},
                          secret, algorithm="HS256")

    def _reject(self, reason: str) -> httpx.Response:
        self.rejections.append(reason)
        return httpx.Response(401, json=UNAUTHORIZED)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        assert request.method == "POST"
        assert request.url.path == "/api/auth/verify-token"
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if scheme != "Bearer" or not token:
            return self._reject("missing")
        try:
            claims = jwt.decode(token, AUTH_SECRET, algorithms=["HS256"],
                                options={"require_sub": True, "require_exp": True, "require_iat": True})
        except ExpiredSignatureError:
            return self._reject("expired")
        except JWTError:
            return self._reject("invalid")
        subject, role = claims["sub"], claims.get("role")
        if not (subject.isascii() and subject.isdecimal()) or not isinstance(role, str) or not role:
            return self._reject("claims")
        user_id = int(subject)
        record = self.users.get(user_id)
        if record is None:
            return self._reject("unknown user")
        if not record["is_active"]:
            return httpx.Response(403, json={"detail": "Inactive user"})
        return httpx.Response(200, json={"valid": True, "user": {
            "id": user_id, "full_name": f"User {user_id}", "email": f"user{user_id}@example.com",
            "role": record["role"], "is_active": True,
        }})


@pytest.fixture
def auth_service() -> StandInAuthService:
    return StandInAuthService()


@pytest.fixture
def http(db_session, auth_service):
    """The real app: test database, real auth dependencies, stand-in Authentication Service."""
    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_auth_client] = lambda: httpx.Client(
        transport=httpx.MockTransport(auth_service.handle))
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin(auth_service) -> dict[str, str]:
    return bearer(auth_service.issue(ADMIN_ID))


@pytest.fixture
def customer(auth_service) -> dict[str, str]:
    return bearer(auth_service.issue(CUSTOMER_ID))


@pytest.fixture
def catalog(http, admin) -> dict:
    """One active category with an active product and an inactive product, made by an admin."""
    category = http.post("/api/categories", json={"name": "Footwear"}, headers=admin).json()
    active = http.post("/api/products", headers=admin, json={
        "sku": "RUN-1", "name": "Runner", "price": "50.00", "category_id": category["id"], "initial_stock": 3,
    }).json()
    hidden = http.post("/api/products", headers=admin, json={
        "sku": "OLD-1", "name": "Old model", "price": "20.00", "category_id": category["id"],
    }).json()
    assert http.delete(f"/api/products/{hidden['id']}", headers=admin).status_code in (200, 204)
    return {"category": category, "active": active, "hidden": hidden}


def admin_requests(catalog: dict) -> list[tuple[str, str, dict | None]]:
    category_id, product_id = catalog["category"]["id"], catalog["active"]["id"]
    return [
        ("post", "/api/categories", {"name": "Bags"}),
        ("patch", f"/api/categories/{category_id}", {"description": "Shoes"}),
        ("delete", f"/api/categories/{category_id}", None),
        ("post", "/api/products", {"sku": "NEW-1", "name": "New", "price": "1.00", "category_id": category_id}),
        ("patch", f"/api/products/{product_id}", {"name": "Runner 2"}),
        ("delete", f"/api/products/{product_id}", None),
        ("get", f"/api/inventory/{product_id}", None),
        ("get", "/api/inventory/low-stock", None),
        ("get", f"/api/inventory/{product_id}/history", None),
        ("post", f"/api/inventory/{product_id}/stock-in", {"quantity": 1}),
        ("post", f"/api/inventory/{product_id}/stock-out", {"quantity": 1}),
    ]


def send(http, method, path, body, headers=None):
    return http.request(method, path, headers=headers or {}, **({"json": body} if body is not None else {}))


# --- Missing tokens ---

def test_missing_token_is_401_on_every_admin_route(http, catalog, auth_service):
    calls_before = auth_service.calls
    for method, path, body in admin_requests(catalog):
        response = send(http, method, path, body)
        assert response.status_code == 401, (method, path)
        assert response.json() == UNAUTHORIZED
        assert response.headers["WWW-Authenticate"] == "Bearer"
    assert auth_service.calls == calls_before  # rejected locally, no call needed


@pytest.mark.parametrize("header", [
    "",                       # empty header
    "Bearer",                 # scheme without a token
    "Bearer ",
    "Basic dXNlcjpwYXNz",     # another scheme
    "Token abc.def.ghi",
])
def test_missing_or_non_bearer_credentials_are_401(http, catalog, header):
    response = http.post("/api/categories", json={"name": "Bags"}, headers={"Authorization": header})
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED


# --- Invalid tokens ---

def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def _tamper_role(token: str, role: str) -> str:
    header, payload, signature = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    return f"{header}.{_b64(claims | {'role': role})}.{signature}"


@pytest.mark.parametrize("make_token", [
    pytest.param(lambda auth: "not-a-jwt", id="garbage"),
    pytest.param(lambda auth: auth.issue(ADMIN_ID, secret="attacker-chosen-secret-0123456789abcdef"),
                 id="wrong-secret"),
    pytest.param(lambda auth: _tamper_role(auth.issue(CUSTOMER_ID), "ADMIN"), id="payload-altered"),
    pytest.param(lambda auth: f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64({'sub': '1', 'role': 'ADMIN'})}.",
                 id="alg-none"),
    pytest.param(lambda auth: auth.issue(999, role="ADMIN"), id="unknown-user"),
    pytest.param(lambda auth: jwt.encode({"sub": "1", "role": "ADMIN"}, AUTH_SECRET, algorithm="HS256"),
                 id="no-exp-or-iat"),
    pytest.param(lambda auth: jwt.encode({"sub": "abc", "role": "ADMIN", "iat": int(time.time()),
                                          "exp": int(time.time()) + 60}, AUTH_SECRET, algorithm="HS256"),
                 id="non-numeric-sub"),
])
def test_invalid_tokens_are_401(http, catalog, auth_service, make_token):
    headers = bearer(make_token(auth_service))
    response = http.post("/api/categories", json={"name": "Bags"}, headers=headers)
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED
    # A token sent to a public route is checked too, never quietly treated as anonymous.
    assert http.get("/api/products", headers=headers).status_code == 401


# --- Expired tokens ---

def test_expired_token_is_401(http, catalog, auth_service):
    expired = bearer(auth_service.issue(ADMIN_ID, lifetime=-60))  # expired a minute ago
    for method, path, body in admin_requests(catalog):
        response = send(http, method, path, body, expired)
        assert response.status_code == 401, (method, path)
        assert response.json() == UNAUTHORIZED
    assert http.get("/api/products", headers=expired).status_code == 401
    # Rejected by the Authentication Service because of exp, not for another reason.
    assert set(auth_service.rejections) == {"expired"}


def test_token_is_accepted_until_it_expires(http, catalog, auth_service):
    almost_expired = bearer(auth_service.issue(ADMIN_ID, lifetime=30))
    assert http.get("/api/inventory/low-stock", headers=almost_expired).status_code == 200


# --- ADMIN access ---

def test_admin_can_manage_categories_products_and_inventory(http, catalog, admin):
    category_id, product_id = catalog["category"]["id"], catalog["active"]["id"]

    new_category = http.post("/api/categories", json={"name": "Bags"}, headers=admin)
    assert new_category.status_code == 201
    assert http.patch(f"/api/categories/{category_id}", json={"description": "Shoes"},
                      headers=admin).status_code == 200
    assert http.delete(f"/api/categories/{new_category.json()['id']}", headers=admin).status_code in (200, 204)

    assert http.patch(f"/api/products/{product_id}", json={"name": "Runner 2"}, headers=admin).status_code == 200
    assert http.post(f"/api/inventory/{product_id}/stock-in", json={"quantity": 5},
                     headers=admin).status_code == 201
    assert http.post(f"/api/inventory/{product_id}/stock-out", json={"quantity": 2},
                     headers=admin).status_code == 201
    stock = http.get(f"/api/inventory/{product_id}", headers=admin)
    assert stock.status_code == 200 and stock.json()["stock_quantity"] == 6
    assert http.get(f"/api/inventory/{product_id}/history", headers=admin).json()["total"] == 3
    assert http.get("/api/inventory/low-stock", headers=admin).status_code == 200


def test_admin_can_see_inactive_records(http, catalog, admin):
    hidden_id = catalog["hidden"]["id"]
    listing = http.get("/api/products", params={"include_inactive": True}, headers=admin)
    assert hidden_id in {item["id"] for item in listing.json()["items"]}
    assert http.get(f"/api/products/{hidden_id}", params={"include_inactive": True},
                    headers=admin).status_code == 200


# --- CUSTOMER (role USER) access ---

def test_customer_can_view_active_products_and_categories(http, catalog, customer):
    category_id, active_id = catalog["category"]["id"], catalog["active"]["id"]

    categories = http.get("/api/categories", headers=customer)
    assert categories.status_code == 200
    assert [item["id"] for item in categories.json()] == [category_id]
    assert http.get(f"/api/categories/{category_id}", headers=customer).status_code == 200

    products = http.get("/api/products", headers=customer)
    assert products.status_code == 200
    assert [item["id"] for item in products.json()["items"]] == [active_id]  # inactive one left out
    assert http.get(f"/api/products/{active_id}", headers=customer).status_code == 200


def test_customer_cannot_see_inactive_records(http, catalog, customer):
    hidden_id = catalog["hidden"]["id"]
    assert http.get(f"/api/products/{hidden_id}", headers=customer).status_code == 404
    for path in ("/api/products", f"/api/products/{hidden_id}", "/api/categories"):
        response = http.get(path, params={"include_inactive": True}, headers=customer)
        assert response.status_code == 403
        assert response.json() == {"detail": "Admin role required"}


def test_customer_is_403_on_every_admin_route(http, catalog, customer, admin):
    for method, path, body in admin_requests(catalog):
        response = send(http, method, path, body, customer)
        assert response.status_code == 403, (method, path)
        assert response.json() == {"detail": "Admin role required"}
    # Nothing was changed by the refused requests.
    product = http.get(f"/api/inventory/{catalog['active']['id']}", headers=admin).json()
    assert product["stock_quantity"] == 3


def test_anonymous_visitors_can_browse(http, catalog, auth_service):
    calls_before = auth_service.calls
    assert http.get("/api/categories").status_code == 200
    assert http.get("/api/products").status_code == 200
    assert http.get(f"/api/products/{catalog['active']['id']}").status_code == 200
    assert auth_service.calls == calls_before  # no token, no verification call


# --- Role decisions use the Authentication Service's answer, not the token ---

def test_role_comes_from_the_auth_service_not_the_token(http, catalog, auth_service):
    # Logged in while ADMIN, then demoted: the token still says ADMIN, but access is refused at once.
    stale_admin = bearer(auth_service.issue(DEMOTED_ID, role=ADMIN_ROLE))
    assert http.post("/api/categories", json={"name": "Bags"}, headers=stale_admin).status_code == 403


def test_roles_are_matched_exactly(http, catalog, auth_service):
    lowercase = bearer(auth_service.issue(LOWERCASE_ADMIN_ID))
    assert http.post("/api/categories", json={"name": "Bags"}, headers=lowercase).status_code == 403


def test_inactive_user_is_403(http, catalog, auth_service):
    inactive = bearer(auth_service.issue(INACTIVE_ID))
    response = http.post("/api/categories", json={"name": "Bags"}, headers=inactive)
    assert response.status_code == 403
    assert response.json() == {"detail": "Inactive user"}


# --- Authentication Service unavailable: fail closed ---

UNAVAILABLE = {"detail": "Authentication service unavailable"}


def _broken(handler):
    app.dependency_overrides[get_auth_client] = lambda: httpx.Client(transport=httpx.MockTransport(handler))


def _raise(error):
    def handler(_request):
        raise error
    return handler


@pytest.mark.parametrize("handler", [
    pytest.param(_raise(httpx.ConnectError("connection refused")), id="down"),
    pytest.param(_raise(httpx.ReadTimeout("timed out")), id="timeout"),
    pytest.param(lambda _r: httpx.Response(500, json={"detail": "Internal server error"}), id="error-500"),
    pytest.param(lambda _r: httpx.Response(503, text="Service Unavailable"), id="error-503"),
    pytest.param(lambda _r: httpx.Response(404, json={"detail": "Not Found"}), id="wrong-url"),
    pytest.param(lambda _r: httpx.Response(302, headers={"Location": "http://elsewhere.test/"}), id="redirect"),
    pytest.param(lambda _r: httpx.Response(200, text="<html>proxy page</html>"), id="not-json"),
    pytest.param(lambda _r: httpx.Response(200, json={"valid": True}), id="incomplete-json"),
])
def test_auth_service_unavailable_fails_closed(http, catalog, admin, handler):
    _broken(handler)
    for method, path, body in admin_requests(catalog):
        response = send(http, method, path, body, admin)
        assert response.status_code == 503, (method, path)
        assert response.json() == UNAVAILABLE
    # A token on a public route cannot be checked either, so it is refused rather than ignored.
    assert http.get("/api/products", headers=admin).status_code == 503
    # Visitors without a token are not affected.
    assert http.get("/api/products").status_code == 200


def test_outage_does_not_leak_the_token(http, catalog, admin, caplog):
    _broken(_raise(httpx.ConnectError("connection refused")))
    with caplog.at_level(logging.DEBUG):
        response = http.post("/api/categories", json={"name": "Bags"}, headers=admin)
    assert response.status_code == 503
    token = admin["Authorization"].removeprefix("Bearer ")
    assert token not in caplog.text
    assert token not in response.text


# --- The reusable dependency factory ---

def test_require_roles_rejects_an_empty_role_list():
    with pytest.raises(ValueError):
        require_roles()
    with pytest.raises(ValueError):
        require_roles("")


def test_require_roles_lists_the_allowed_roles(http, catalog, auth_service):
    from fastapi import APIRouter, Depends

    router = APIRouter()

    @router.get("/_test/staff", include_in_schema=False,
                dependencies=[Depends(require_roles(ADMIN_ROLE, "STAFF"))])
    def staff_only():
        return {"ok": True}

    app.include_router(router)
    try:
        customer = bearer(auth_service.issue(CUSTOMER_ID))
        response = http.get("/_test/staff", headers=customer)
        assert response.status_code == 403
        assert response.json() == {"detail": "One of these roles is required: ADMIN, STAFF"}
        assert http.get("/_test/staff", headers=bearer(auth_service.issue(ADMIN_ID))).json() == {"ok": True}
        assert http.get("/_test/staff").status_code == 401
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/_test/staff"]
        app.openapi_schema = None  # drop any schema cached while the test route existed
