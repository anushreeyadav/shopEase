"""Authentication through the Authentication Service, with its verify-token endpoint mocked.

Mocked responses copy the real ones from shopease-auth-service (auth_routes.verify_token,
TokenVerificationResponse, PROTECTED_ROUTE_ERRORS, exception handlers). The tests call a small
app over HTTP, so the bearer parsing, status codes, and headers are those a client sees.
"""

import logging
from collections.abc import Callable

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.security import (
    MAX_DB_INT,
    MAX_TOKEN_LENGTH,
    AuthenticatedUser,
    get_auth_client,
    get_current_authenticated_user,
    require_admin,
)
from tests.conftest import VERIFIED_USER

VERIFY_URL = "http://auth.test/api/auth/verify-token"
TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI3In0.test-signature-not-real"

# Real Authentication Service responses.
AUTH_OK = (200, {"valid": True, "user": VERIFIED_USER})
AUTH_INVALID = (401, {"detail": "Could not validate credentials"})
AUTH_INACTIVE = (403, {"detail": "Inactive user"})
AUTH_DB_DOWN = (503, {"detail": "Service temporarily unavailable"})
AUTH_ERROR = (500, {"detail": "Internal server error"})

app = FastAPI()


@app.get("/whoami")
def whoami(user: AuthenticatedUser = Depends(get_current_authenticated_user)):
    return {"auth_user_id": user.auth_user_id, "role": user.role}


@app.post("/whoami")
def whoami_with_body(body: dict, user: AuthenticatedUser = Depends(get_current_authenticated_user)):
    # A client-supplied auth_user_id is ignored: the identity comes only from verification.
    return {"auth_user_id": user.auth_user_id}


@app.get("/admin-only")
def admin_only(user: AuthenticatedUser = Depends(require_admin)):
    return {"ok": True}


class FakeAuthService:
    """Records the requests it receives and answers them with handler."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]):
        self.requests: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        self.client = httpx.Client(transport=httpx.MockTransport(record), follow_redirects=False)


@pytest.fixture
def auth_service():
    """Return a function that installs a fake Authentication Service and gives an HTTP test client."""

    def install(response: tuple[int, object] | Callable[[httpx.Request], httpx.Response] = AUTH_OK):
        if callable(response):
            handler = response
        else:
            code, body = response
            handler = lambda _request: httpx.Response(code, json=body)  # noqa: E731
        fake = FakeAuthService(handler)
        app.dependency_overrides[get_auth_client] = lambda: fake.client
        return fake, TestClient(app)

    yield install
    app.dependency_overrides.clear()


def bearer(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_unauthenticated(response: httpx.Response) -> None:
    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
    assert response.headers["WWW-Authenticate"] == "Bearer"


# --- Valid token -------------------------------------------------------------------------

def test_valid_token_authenticates_the_verified_user(auth_service):
    fake, client = auth_service(AUTH_OK)

    response = client.get("/whoami", headers=bearer())

    assert response.status_code == 200
    assert response.json() == {"auth_user_id": 7, "role": "USER"}


def test_token_is_forwarded_unchanged_to_the_configured_url(auth_service):
    fake, client = auth_service(AUTH_OK)

    client.get("/whoami", headers=bearer())

    (request,) = fake.requests
    assert request.method == "POST"
    assert str(request.url) == VERIFY_URL
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.content == b""


def test_lowercase_bearer_scheme_is_accepted(auth_service):
    _, client = auth_service(AUTH_OK)
    assert client.get("/whoami", headers={"Authorization": f"bearer {TOKEN}"}).status_code == 200


def test_client_supplied_auth_user_id_is_ignored(auth_service):
    _, client = auth_service(AUTH_OK)

    response = client.post(
        "/whoami?auth_user_id=999",
        json={"auth_user_id": 999},
        headers={**bearer(), "X-User-Id": "999", "X-Auth-User-Id": "999"},
    )

    assert response.json() == {"auth_user_id": 7}


@pytest.mark.parametrize(("sent_id", "expected"), [(42, 42), ("42", 42), (MAX_DB_INT, MAX_DB_INT)])
def test_user_id_is_converted_to_the_database_integer_type(auth_service, sent_id, expected):
    _, client = auth_service((200, {"valid": True, "user": {**VERIFIED_USER, "id": sent_id}}))

    body = client.get("/whoami", headers=bearer()).json()

    assert body["auth_user_id"] == expected
    assert type(body["auth_user_id"]) is int


def test_extra_fields_from_the_auth_service_are_tolerated(auth_service):
    _, client = auth_service((200, {"valid": True, "user": {**VERIFIED_USER, "new_field": 1}, "also": "new"}))
    assert client.get("/whoami", headers=bearer()).status_code == 200


# --- Missing or invalid token: 401 --------------------------------------------------------

@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": ""},
    {"Authorization": "Bearer"},
    {"Authorization": "Bearer "},
    {"Authorization": f"Basic {TOKEN}"},
    {"Authorization": TOKEN},
    {"Authorization": "Bearer " + "a" * (MAX_TOKEN_LENGTH + 1)},
])
def test_missing_or_unusable_token_is_rejected_without_calling_the_auth_service(auth_service, headers):
    fake, client = auth_service(AUTH_OK)

    response = client.get("/whoami", headers=headers)

    assert_unauthenticated(response)
    assert fake.requests == []


@pytest.mark.parametrize("reason", ["invalid signature", "expired", "malformed", "user deleted"])
def test_token_rejected_by_the_auth_service_gives_401(auth_service, reason):
    # The Authentication Service answers all of these with the same 401.
    _, client = auth_service(AUTH_INVALID)
    assert_unauthenticated(client.get("/whoami", headers=bearer(f"token-{reason.replace(' ', '-')}")))


def test_valid_false_in_a_200_response_gives_401(auth_service):
    _, client = auth_service((200, {"valid": False, "user": VERIFIED_USER}))
    assert_unauthenticated(client.get("/whoami", headers=bearer()))


# --- Inactive user: 403 -------------------------------------------------------------------

def test_inactive_user_gives_403(auth_service):
    _, client = auth_service(AUTH_INACTIVE)

    response = client.get("/whoami", headers=bearer())

    assert response.status_code == 403
    assert response.json() == {"detail": "Inactive user"}


def test_inactive_flag_in_a_200_response_gives_403(auth_service):
    _, client = auth_service((200, {"valid": True, "user": {**VERIFIED_USER, "is_active": False}}))
    assert client.get("/whoami", headers=bearer()).status_code == 403


# --- Malformed verification response: 503, never trusted -----------------------------------

def _with_user(**changes):
    return (200, {"valid": True, "user": {**VERIFIED_USER, **changes}})


@pytest.mark.parametrize("response", [
    (200, {"valid": True}),
    (200, {"user": VERIFIED_USER}),
    (200, {"unexpected": "shape"}),
    (200, []),
    (200, None),
    _with_user(id=True),
    _with_user(id=0),
    _with_user(id=-7),
    _with_user(id=MAX_DB_INT + 1),
    _with_user(id=7.5),
    _with_user(id="7a"),
    _with_user(id="٣"),  # a non-ASCII digit
    _with_user(id=None),
    _with_user(role=""),
    _with_user(is_active="maybe"),
    _with_user(email=None),
], ids=lambda value: str(value)[:60])
def test_malformed_verification_response_fails_closed(auth_service, response):
    _, client = auth_service(response)

    result = client.get("/whoami", headers=bearer())

    assert result.status_code == 503
    assert result.json() == {"detail": "Authentication service unavailable"}


def test_non_json_verification_response_fails_closed(auth_service):
    _, client = auth_service(lambda _request: httpx.Response(200, text="<html>ok</html>"))
    assert client.get("/whoami", headers=bearer()).status_code == 503


# --- Authentication Service unavailable: 503 -----------------------------------------------

@pytest.mark.parametrize("response", [AUTH_DB_DOWN, AUTH_ERROR, (404, {"detail": "Not Found"}), (502, {})])
def test_auth_service_error_status_gives_503(auth_service, response):
    _, client = auth_service(response)
    assert client.get("/whoami", headers=bearer()).status_code == 503


def test_redirect_is_not_followed(auth_service):
    fake, client = auth_service(
        lambda _request: httpx.Response(302, headers={"Location": "http://elsewhere.test/steal"})
    )

    assert client.get("/whoami", headers=bearer()).status_code == 503
    assert [str(request.url) for request in fake.requests] == [VERIFY_URL]


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError])
def test_unreachable_auth_service_gives_503(auth_service, error):
    def fail(request: httpx.Request) -> httpx.Response:
        raise error("failure", request=request)

    _, client = auth_service(fail)
    response = client.get("/whoami", headers=bearer())

    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication service unavailable"}


def test_configured_timeout_is_applied():
    get_auth_client.cache_clear()
    try:
        timeout = get_auth_client().timeout
        assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (2, 2, 2, 2)
        assert get_auth_client().follow_redirects is False
    finally:
        get_auth_client().close()
        get_auth_client.cache_clear()


# --- The token never leaks ------------------------------------------------------------------

@pytest.mark.parametrize("response", [
    AUTH_OK, AUTH_INVALID, AUTH_INACTIVE, AUTH_ERROR, (200, {"bad": "body"}),
    lambda request: (_ for _ in ()).throw(httpx.ConnectTimeout("timed out", request=request)),
])
def test_token_never_appears_in_logs_or_responses(auth_service, caplog, response):
    secret_token = "eyJsecret.token-value-that-must-not-leak.sig"
    _, client = auth_service(response)

    with caplog.at_level(logging.DEBUG):
        result = client.get("/whoami", headers=bearer(secret_token))

    assert secret_token not in caplog.text
    assert secret_token not in result.text
    assert secret_token not in str(result.headers)


# --- Roles -----------------------------------------------------------------------------------

def test_admin_route_rejects_a_user_role(auth_service):
    _, client = auth_service(AUTH_OK)

    response = client.get("/admin-only", headers=bearer())

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin role required"}


def test_admin_route_accepts_the_admin_role(auth_service):
    _, client = auth_service(_with_user(role="ADMIN"))
    assert client.get("/admin-only", headers=bearer()).status_code == 200
