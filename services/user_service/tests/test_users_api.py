"""User API tests: authentication, profile, addresses, cross-user isolation, admin, internal."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import Database
from app.main import create_app
from app.models import Base
from shopease_shared.security import JWKSKeyProvider
from tests.jwt_helpers import KEY_PROVIDER, OTHER_KEY, bearer, make_token

ADDRESS = {
    "label": "Home",
    "line1": "12 Example Street",
    "line2": "Flat 4B",
    "city": "Pune",
    "state": "Maharashtra",
    "postal_code": "411001",
    "country": "IN",
    "is_default": False,
}


@pytest.fixture
def client():
    app = create_app(Settings(_env_file=None, APP_ENV="test"), key_provider=KEY_PROVIDER)
    db = Database("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(db.engine)
    app.state.db = db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    db.dispose()


class User:
    def __init__(self, client: TestClient, role: str = "customer"):
        self.id = uuid.uuid4()
        self.client = client
        self.headers = bearer(make_token(self.id, role=role))

    def get(self, path, **kw):
        return self.client.get(path, headers=self.headers, **kw)

    def add_address(self, **overrides):
        response = self.client.post("/api/users/me/addresses", headers=self.headers, json={**ADDRESS, **overrides})
        assert response.status_code == 201, response.text
        return response.json()


# --- Authentication at the service boundary ------------------------------------------


@pytest.mark.parametrize(
    "headers,code",
    [
        ({}, "UNAUTHENTICATED"),
        ({"Authorization": "Basic abc"}, "UNAUTHENTICATED"),
        (bearer("garbage"), "INVALID_TOKEN"),
        (bearer(make_token(expires_in=-120)), "TOKEN_EXPIRED"),
        (bearer(make_token(key=OTHER_KEY)), "INVALID_TOKEN"),
        (bearer(make_token(kid="unknown-kid")), "INVALID_TOKEN"),
        (bearer(make_token(aud="shopease-internal")), "INVALID_TOKEN"),
        (bearer(make_token(iss="someone-else")), "INVALID_TOKEN"),
        (bearer(make_token(algorithm="none")), "INVALID_TOKEN"),
        (bearer(make_token("svc:order", token_use="service", scope="addresses:read")), "INVALID_TOKEN"),
    ],
    ids=["missing", "basic", "garbage", "expired", "wrong-key", "unknown-kid", "wrong-aud", "wrong-iss", "alg-none", "service-token"],
)
def test_user_routes_reject_missing_or_invalid_tokens(client, headers, code):
    response = client.get("/api/users/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == code
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_identity_headers_from_clients_are_ignored(client):
    victim = User(client)
    victim.get("/api/users/me")
    spoof = {"X-User-Id": str(victim.id), "X-User-Token": "anything", "X-Forwarded-User": str(victim.id)}
    assert client.get("/api/users/me", headers=spoof).status_code == 401
    attacker = User(client)
    response = client.get("/api/users/me", headers={**attacker.headers, **spoof})
    assert response.json()["user_id"] == str(attacker.id)


def test_unreachable_jwks_gives_503_not_a_bypass():
    app = create_app(
        Settings(_env_file=None, APP_ENV="test"),
        key_provider=JWKSKeyProvider("http://127.0.0.1:1/jwks.json", timeout_seconds=1),
    )
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/api/users/me", headers=bearer(make_token()))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AUTH_UNAVAILABLE"


# --- Profile ---------------------------------------------------------------------------


def test_me_creates_the_profile_on_first_access(client):
    user = User(client)
    first = user.get("/api/users/me")
    assert first.status_code == 200
    assert first.json() | {"created_at": None, "updated_at": None} == {
        "user_id": str(user.id),
        "full_name": None,
        "phone": None,
        "contact_email": None,
        "created_at": None,
        "updated_at": None,
    }
    assert user.get("/api/users/me").json()["created_at"] == first.json()["created_at"]


def test_profile_update_changes_only_the_fields_sent(client):
    user = User(client)
    response = client.patch("/api/users/me", headers=user.headers, json={"full_name": "Asha Rao", "phone": "+91-90000-00000"})
    assert response.status_code == 200
    response = client.patch("/api/users/me", headers=user.headers, json={"phone": None})
    body = response.json()
    assert body["full_name"] == "Asha Rao" and body["phone"] is None
    assert user.get("/api/users/me").json()["full_name"] == "Asha Rao"


@pytest.mark.parametrize(
    "body",
    [{"user_id": str(uuid.uuid4())}, {"contact_email": "not-an-email"}, {"full_name": "x" * 201}],
    ids=["cannot-change-identity", "bad-email", "too-long"],
)
def test_profile_update_validation(client, body):
    user = User(client)
    response = client.patch("/api/users/me", headers=user.headers, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "not-an-email" not in response.text


# --- Addresses -------------------------------------------------------------------------


def test_address_lifecycle_and_default_handling(client):
    user = User(client)
    first = user.add_address(label="Home")
    assert first["is_default"] is True  # the first address becomes the default
    second = user.add_address(label="Work", is_default=True)
    listing = user.get("/api/users/me/addresses").json()
    assert listing["total"] == 2 and listing["limit"] == 20 and listing["offset"] == 0
    defaults = {a["label"]: a["is_default"] for a in listing["items"]}
    assert defaults == {"Home": False, "Work": True}

    replaced = client.put(
        f"/api/users/me/addresses/{first['address_id']}", headers=user.headers, json={**ADDRESS, "city": "Mumbai", "is_default": True}
    )
    assert replaced.status_code == 200 and replaced.json()["city"] == "Mumbai"
    assert [a["label"] for a in user.get("/api/users/me/addresses").json()["items"] if a["is_default"]] == ["Home"]

    assert client.delete(f"/api/users/me/addresses/{second['address_id']}", headers=user.headers).status_code == 204
    assert user.get("/api/users/me/addresses").json()["total"] == 1


def test_address_pagination_and_validation(client):
    user = User(client)
    for i in range(3):
        user.add_address(label=f"A{i}")
    page = user.get("/api/users/me/addresses", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 3 and len(page["items"]) == 1
    assert user.get("/api/users/me/addresses", params={"limit": 0}).status_code == 422
    bad = client.post("/api/users/me/addresses", headers=user.headers, json={**ADDRESS, "country": "India"})
    assert bad.status_code == 422
    missing = client.put(f"/api/users/me/addresses/{uuid.uuid4()}", headers=user.headers, json={"line1": "x"})
    assert missing.status_code == 422  # PUT replaces the whole address: every field is required
    malformed = client.delete("/api/users/me/addresses/not-a-uuid", headers=user.headers)
    assert malformed.status_code == 422 and "not-a-uuid" not in malformed.text


def test_users_cannot_see_or_change_each_others_addresses(client):
    owner, other = User(client), User(client)
    address = owner.add_address(label="Home")
    path = f"/api/users/me/addresses/{address['address_id']}"

    assert other.get("/api/users/me/addresses").json()["total"] == 0
    for response in (
        client.put(path, headers=other.headers, json={**ADDRESS, "city": "Hijacked"}),
        client.delete(path, headers=other.headers),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "ADDRESS_NOT_FOUND"

    [still_there] = owner.get("/api/users/me/addresses").json()["items"]
    assert still_there["city"] == "Pune"
    # Setting a default in another account never touches this owner's default.
    other.add_address(label="Theirs", is_default=True)
    assert owner.get("/api/users/me/addresses").json()["items"][0]["is_default"] is True


# --- Admin -----------------------------------------------------------------------------


def test_only_admins_can_read_other_profiles(client):
    target = User(client)
    target.get("/api/users/me")
    customer, admin = User(client), User(client, role="admin")

    denied = customer.get(f"/api/users/{target.id}")
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "FORBIDDEN"
    assert admin.get(f"/api/users/{target.id}").json()["user_id"] == str(target.id)
    assert admin.get(f"/api/users/{uuid.uuid4()}").status_code == 404


# --- Internal address lookup (service token + forwarded user token) --------------------


def test_internal_address_lookup_requires_service_scope_and_the_owners_token(client):
    owner, other = User(client), User(client)
    address = owner.add_address()
    path = f"/internal/users/{owner.id}/addresses/{address['address_id']}"
    service = bearer(make_token("svc:order", token_use="service", scope="addresses:read products:read"))
    owner_token = {"X-User-Token": make_token(owner.id)}

    assert client.get(path).status_code == 401
    assert client.get(path, headers={**owner.headers, **owner_token}).status_code == 401  # user token is not a service token
    no_scope = bearer(make_token("svc:payment", token_use="service", scope="orders:read"))
    denied = client.get(path, headers={**no_scope, **owner_token})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "INSUFFICIENT_SCOPE"
    assert client.get(path, headers=service).status_code == 401  # no forwarded user
    assert client.get(path, headers={**service, "X-User-Token": "forged"}).status_code == 401
    wrong_user = client.get(path, headers={**service, "X-User-Token": make_token(other.id)})
    assert wrong_user.status_code == 404

    ok = client.get(path, headers={**service, **owner_token})
    assert ok.status_code == 200 and ok.json()["address_id"] == address["address_id"]


# --- Transaction rollback ---------------------------------------------------------------------------


def test_a_failure_mid_request_rolls_back_the_address(client, monkeypatch):
    from app import profiles

    user = User(client)
    user.get("/api/users/me")  # profile exists

    def fail_after_flush(session, *args, **kwargs):
        session.flush()  # the new address row is written inside the transaction
        raise RuntimeError("simulated failure; internal detail")

    monkeypatch.setattr(profiles, "_clear_other_defaults", fail_after_flush)
    response = client.post("/api/users/me/addresses", headers=user.headers, json={**ADDRESS, "is_default": True})
    assert response.status_code == 500 and response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "simulated" not in response.text
    monkeypatch.undo()
    assert user.get("/api/users/me/addresses").json()["total"] == 0
