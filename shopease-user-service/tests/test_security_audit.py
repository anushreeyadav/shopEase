"""Security audit: one customer must never reach another customer's profile or addresses.

Unlike the other API tests, these do not override get_current_authenticated_user. Every request
carries a real signed JWT and goes through the real verification code, which calls a stand-in
Authentication Service (tests/fake_auth_service.py) that follows the real service's contract.

TC01-TC20 are the audit test cases, in order. SR-* tests check the security requirements
across every endpoint.
"""

import logging
import re
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.security import get_auth_client
from app.database.connection import get_db
from app.main import app
from app.models import UserAddress, UserProfile
from app.services import address_service, user_service
from tests.fake_auth_service import FakeAuthService, VERIFY_PATH, default_users, sign_token

PROFILE = "/api/users/profile"
ADDRESSES = "/api/users/addresses"
ACCOUNT = "/api/users/account"

HOME = {
    "address_type": "HOME", "full_name": "Asha Rao", "phone_number": "+91 98765-43210",
    "address_line_1": "12 MG Road", "city": "Bengaluru", "state": "Karnataka",
    "country": "India", "postal_code": "560001",
}
OFFICE = {**HOME, "address_type": "OFFICE", "address_line_1": "1 Tech Park", "postal_code": "560103"}

# Taken from the app's OpenAPI schema (every route is included in it), so a new endpoint is
# picked up automatically by the all-endpoint tests below.
API_ROUTES = sorted(
    (method.upper(), path)
    for path, operations in app.openapi()["paths"].items()
    if path.startswith("/api/")
    for method in operations
)
# Every route that needs an active local profile: all API routes except GET /api/users/account,
# which also works before a profile exists.
PROFILE_ROUTES = [r for r in API_ROUTES if r != ("GET", ACCOUNT)]
ADDRESS_ROUTES = [r for r in API_ROUTES if r[1].startswith(ADDRESSES)]


class Audit:
    """The app with a test database and the stand-in Authentication Service."""

    def __init__(self, client: TestClient, auth: FakeAuthService, db):
        self.client, self.auth, self.db = client, auth, db
        self.tokens = {uid: auth.issue_token(uid) for uid in auth.users}

    def headers(self, user_id: int) -> dict:
        return {"Authorization": f"Bearer {self.tokens[user_id]}"}

    def call(self, user_id: int | None, method: str, url: str, body=None, **kwargs):
        headers = {**(self.headers(user_id) if user_id else {}), **kwargs.pop("headers", {})}
        return self.client.request(method, url, json=body, headers=headers, **kwargs)

    def create_profile(self, user_id: int, **fields) -> dict:
        response = self.call(user_id, "POST", PROFILE, {"full_name": f"Customer {user_id}", **fields})
        assert response.status_code == 201, response.text
        return response.json()

    def add_address(self, user_id: int, body: dict = HOME, **changes) -> dict:
        response = self.call(user_id, "POST", ADDRESSES, {**body, **changes})
        assert response.status_code == 201, response.text
        return response.json()

    def profile_row(self, auth_user_id: int) -> UserProfile:
        self.db.expire_all()
        return self.db.scalars(select(UserProfile).where(UserProfile.auth_user_id == auth_user_id)).one()

    def address_row(self, address_id: int) -> UserAddress | None:
        self.db.expire_all()
        return self.db.get(UserAddress, address_id)

    def default_ids(self, profile_id: int) -> list[int]:
        self.db.expire_all()
        return list(self.db.scalars(select(UserAddress.id).where(
            UserAddress.user_id == profile_id, UserAddress.is_default.is_(True))))


@pytest.fixture
def audit(db_session) -> Iterator[Audit]:
    auth = FakeAuthService(default_users())
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_auth_client] = auth.client
    try:
        # raise_server_exceptions=False: see the response a real client would get on a 500.
        yield Audit(TestClient(app, raise_server_exceptions=False), auth, db_session)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def two_customers(audit) -> dict:
    """Customer 7 (victim) with two addresses, and customer 8 (attacker) with one."""
    victim_profile = audit.create_profile(7, phone_number="9876543210")
    victim_home = audit.add_address(7)
    victim_office = audit.add_address(7, OFFICE)
    attacker_profile = audit.create_profile(8)
    attacker_home = audit.add_address(8, full_name="Ravi Kumar")
    return {"victim": victim_profile, "victim_home": victim_home, "victim_office": victim_office,
            "attacker": attacker_profile, "attacker_home": attacker_home}


def fill(path: str, address_id: int = 1) -> str:
    return path.replace("{address_id}", str(address_id))


def body_for(method: str, path: str) -> dict | None:
    if method in ("POST", "PUT") and path.startswith(ADDRESSES):
        return HOME
    if method in ("POST", "PUT", "PATCH") and path == PROFILE:
        return {"full_name": "Someone"}
    if path.endswith("/contact"):
        return {"phone_number": "9876543210"}
    return None


UNAUTHORIZED = {"detail": "Could not validate credentials"}
NOT_FOUND = {"detail": "Address not found"}
DEACTIVATED = {"detail": "User profile is deactivated"}


# === TC01-TC08: authentication and profiles ===================================================

def test_tc01_profile_without_jwt(audit):
    response = audit.call(None, "GET", PROFILE)

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert audit.auth.requests == []  # rejected before the Authentication Service is asked


@pytest.mark.parametrize("token", [
    "not-a-jwt",
    "a.b.c",
    sign_token({"sub": "7", "role": "USER", "iat": 0, "exp": 4102444800}, key=b"attacker-chosen-key"),
    sign_token({"sub": "7", "role": "ADMIN", "iat": 0, "exp": 4102444800}, alg="none").rsplit(".", 1)[0] + ".",
    "x" * 5000,
], ids=["garbage", "three-parts", "wrong-signing-key", "alg-none", "oversized"])
def test_tc02_profile_with_invalid_jwt(audit, token):
    audit.create_profile(7)

    response = audit.call(None, "GET", PROFILE, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED
    assert "Asha" not in response.text and "Customer 7" not in response.text


def test_tc02_tampered_payload_cannot_switch_user(audit):
    audit.create_profile(7)
    header, _payload, signature = audit.tokens[8].split(".")
    forged_payload = audit.tokens[7].split(".")[1]  # customer 7's claims with customer 8's signature

    response = audit.call(None, "GET", PROFILE,
                          headers={"Authorization": f"Bearer {header}.{forged_payload}.{signature}"})

    assert response.status_code == 401


@pytest.mark.parametrize("scheme", ["Basic", "Token", "bearer-x"])
def test_tc02_non_bearer_scheme(audit, scheme):
    response = audit.call(None, "GET", PROFILE, headers={"Authorization": f"{scheme} {audit.tokens[7]}"})
    assert response.status_code == 401


def test_tc03_profile_with_expired_jwt(audit):
    audit.create_profile(7)
    expired = audit.auth.issue_token(7, expires_in=-1)

    response = audit.call(None, "GET", PROFILE, headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED
    assert len(audit.auth.requests) == 2  # the create, then this check: expiry is decided by the auth service


def test_tc04_profile_with_valid_jwt(audit):
    created = audit.create_profile(7)

    response = audit.call(7, "GET", PROFILE)

    assert response.status_code == 200
    assert response.json() == created
    verify = audit.auth.requests[-1]
    assert (verify.method, verify.url.path, verify.content) == ("POST", VERIFY_PATH, b"")
    assert verify.headers["Authorization"] == f"Bearer {audit.tokens[7]}"


def test_tc05_duplicate_profile(audit):
    audit.create_profile(7)

    response = audit.call(7, "POST", PROFILE, {"full_name": "Second Profile"})

    assert response.status_code == 409
    assert response.json() == {"detail": "User profile already exists"}
    count = audit.db.scalar(select(func.count()).select_from(UserProfile).where(UserProfile.auth_user_id == 7))
    assert count == 1
    assert audit.profile_row(7).full_name == "Customer 7"


def test_tc06_retrieve_own_profile(audit):
    audit.create_profile(7, phone_number="9876543210")
    audit.create_profile(8)

    body = audit.call(7, "GET", PROFILE).json()

    assert body["auth_user_id"] == 7
    assert body["full_name"] == "Customer 7"
    assert body["phone_number"] == "9876543210"


def test_tc07_update_own_profile(audit):
    audit.create_profile(7)

    patched = audit.call(7, "PATCH", PROFILE, {"phone_number": "0091 98765 43210"})
    replaced = audit.call(7, "PUT", PROFILE, {"full_name": "Asha R.", "gender": "FEMALE"})

    assert patched.status_code == 200 and patched.json()["phone_number"] == "+919876543210"
    assert replaced.status_code == 200
    row = audit.profile_row(7)
    assert (row.full_name, row.gender.value, row.phone_number) == ("Asha R.", "FEMALE", None)


class TestTC08AnotherUsersProfile:
    """Customer 8 tries every available way to read or change customer 7's profile."""

    def test_own_token_only_ever_returns_own_profile(self, audit, two_customers):
        body = audit.call(8, "GET", PROFILE).json()
        assert body["auth_user_id"] == 8 and body["id"] == two_customers["attacker"]["id"]

    @pytest.mark.parametrize("params", [{"auth_user_id": 7}, {"user_id": 7}, {"id": 1}, {"profile_id": 1}])
    def test_query_parameters_are_ignored(self, audit, two_customers, params):
        body = audit.call(8, "GET", PROFILE, params=params).json()
        assert body["auth_user_id"] == 8

    @pytest.mark.parametrize("header", ["X-User-Id", "X-Auth-User-Id", "X-Forwarded-User", "X-Remote-User"])
    def test_identity_headers_are_ignored(self, audit, two_customers, header):
        body = audit.call(8, "GET", PROFILE, headers={header: "7"}).json()
        assert body["auth_user_id"] == 8

    @pytest.mark.parametrize("field", ["auth_user_id", "id", "user_id", "is_active", "email", "role"])
    def test_identity_fields_in_the_body_are_rejected(self, audit, two_customers, field):
        response = audit.call(8, "PATCH", PROFILE, {"full_name": "Hacked", field: 7})

        assert response.status_code == 422
        assert audit.profile_row(7).full_name == "Customer 7"
        assert audit.profile_row(8).full_name == "Customer 8"

    @pytest.mark.parametrize(("method", "path"), [
        ("GET", "/api/users/7"), ("GET", "/api/users/profile/7"), ("GET", "/api/users/1"),
        ("PATCH", "/api/users/7"), ("DELETE", "/api/users/7"), ("GET", "/api/users/7/profile"),
    ])
    def test_there_is_no_route_that_takes_a_user_id(self, audit, two_customers, method, path):
        response = audit.call(8, method, path, {"full_name": "Hacked"})

        assert response.status_code in (404, 405)
        assert "Customer 7" not in response.text and "9876543210" not in response.text

    def test_writes_never_reach_the_other_profile(self, audit, two_customers):
        audit.call(8, "PUT", PROFILE, {"full_name": "Hacked"}, params={"auth_user_id": 7})
        audit.call(8, "PATCH", f"{ACCOUNT}/contact", {"phone_number": "9000000000"}, headers={"X-User-Id": "7"})
        audit.call(8, "PATCH", f"{ACCOUNT}/deactivate", params={"auth_user_id": 7})

        victim = audit.profile_row(7)
        assert (victim.full_name, victim.phone_number, victim.is_active) == ("Customer 7", "9876543210", True)
        assert audit.profile_row(8).is_active is False  # the attacker deactivated only themself

    def test_account_endpoint_shows_only_the_token_identity(self, audit, two_customers):
        body = audit.call(8, "GET", ACCOUNT, params={"auth_user_id": 7}, headers={"X-User-Id": "7"}).json()
        assert body["authentication_account"]["auth_user_id"] == 8
        assert body["authentication_account"]["email"] == "ravi.test@example.com"
        assert body["profile"]["auth_user_id"] == 8


# === TC09-TC17: addresses ======================================================================

def test_tc09_create_own_address(audit):
    profile = audit.create_profile(7)

    response = audit.call(7, "POST", ADDRESSES, HOME, params={"user_id": 999})

    assert response.status_code == 201
    assert response.json()["user_id"] == profile["id"]
    assert audit.address_row(response.json()["id"]).user_id == profile["id"]


def test_tc10_retrieve_own_addresses(audit, two_customers):
    response = audit.call(7, "GET", ADDRESSES, params={"user_id": two_customers["attacker"]["id"]})

    assert response.status_code == 200
    ids = {a["id"] for a in response.json()}
    assert ids == {two_customers["victim_home"]["id"], two_customers["victim_office"]["id"]}
    assert all(a["user_id"] == two_customers["victim"]["id"] for a in response.json())


def test_tc11_update_own_address(audit, two_customers):
    address_id = two_customers["victim_home"]["id"]

    response = audit.call(7, "PUT", f"{ADDRESSES}/{address_id}", {**HOME, "city": "Mysuru"})

    assert response.status_code == 200
    assert audit.address_row(address_id).city == "Mysuru"


def test_tc12_delete_own_address(audit, two_customers):
    address_id = two_customers["victim_office"]["id"]

    response = audit.call(7, "DELETE", f"{ADDRESSES}/{address_id}")

    assert response.status_code == 200
    assert audit.address_row(address_id) is None


def test_tc13_cannot_read_another_users_address_by_changing_address_id(audit, two_customers):
    victim_ids = {two_customers["victim_home"]["id"], two_customers["victim_office"]["id"]}
    own_id = two_customers["attacker_home"]["id"]
    missing = audit.call(8, "GET", f"{ADDRESSES}/999999")

    # Walk through every nearby ID, as an attacker enumerating addresses would.
    for address_id in range(1, max(victim_ids | {own_id}) + 5):
        response = audit.call(8, "GET", f"{ADDRESSES}/{address_id}")
        if address_id == own_id:
            assert response.status_code == 200
            continue
        assert response.status_code == 404, address_id
        assert response.json() == missing.json() == NOT_FOUND
        assert response.headers.get("content-length") == missing.headers.get("content-length")


@pytest.mark.parametrize(("method", "suffix", "body"), [
    ("PUT", "", {**HOME, "full_name": "Hacked", "city": "Elsewhere"}),
    ("DELETE", "", None),
    ("PATCH", "/default", None),
])
def test_tc14_cannot_modify_another_users_address(audit, two_customers, method, suffix, body):
    target = two_customers["victim_office"]  # not the victim's default
    before = audit.address_row(target["id"])
    snapshot = (before.full_name, before.city, before.is_default)

    response = audit.call(8, method, f"{ADDRESSES}/{target['id']}{suffix}", body,
                          params={"user_id": two_customers["victim"]["id"], "auth_user_id": 7},
                          headers={"X-User-Id": "7"})

    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    after = audit.address_row(target["id"])
    assert after is not None and (after.full_name, after.city, after.is_default) == snapshot
    assert audit.default_ids(two_customers["victim"]["id"]) == [two_customers["victim_home"]["id"]]
    assert audit.default_ids(two_customers["attacker"]["id"]) == [two_customers["attacker_home"]["id"]]


def test_tc14_cannot_move_an_address_to_another_owner(audit, two_customers):
    target = two_customers["attacker_home"]["id"]

    response = audit.call(8, "PUT", f"{ADDRESSES}/{target}", {**HOME, "user_id": two_customers["victim"]["id"]})

    assert response.status_code == 422
    assert audit.address_row(target).user_id == two_customers["attacker"]["id"]


def test_tc15_set_an_address_as_default(audit, two_customers):
    office = two_customers["victim_office"]["id"]

    response = audit.call(7, "PATCH", f"{ADDRESSES}/{office}/default")

    assert response.status_code == 200 and response.json()["is_default"] is True
    assert audit.default_ids(two_customers["victim"]["id"]) == [office]
    assert audit.call(7, "GET", f"{ADDRESSES}/default").json()["id"] == office


def test_tc16_two_defaults_through_the_api(audit):
    profile = audit.create_profile(7)

    first = audit.add_address(7, is_default=True)
    second = audit.add_address(7, OFFICE, is_default=True)
    put = audit.call(7, "PUT", f"{ADDRESSES}/{first['id']}", {**HOME, "is_default": True})

    assert put.status_code == 422  # is_default cannot be set through PUT
    assert audit.default_ids(profile["id"]) == [second["id"]]


def test_tc16_two_defaults_directly_in_the_database(audit):
    profile = audit.create_profile(7)
    audit.add_address(7)
    row = {k: v for k, v in HOME.items()} | {"phone_number": "9876543210"}

    # Even code that bypasses the service cannot store a second default: the unique key refuses it.
    with pytest.raises(IntegrityError):
        with audit.db.begin_nested():
            audit.db.add(UserAddress(user_id=profile["id"], is_default=True, **row))
            audit.db.flush()
    assert len(audit.default_ids(profile["id"])) == 1


def test_tc17_only_one_default_exists_after_every_operation(audit):
    profile = audit.create_profile(7)
    ids = [audit.add_address(7, is_default=n % 2 == 0)["id"] for n in range(4)]

    operations = [("PATCH", f"{ADDRESSES}/{ids[1]}/default"), ("PATCH", f"{ADDRESSES}/{ids[3]}/default"),
                  ("DELETE", f"{ADDRESSES}/{ids[3]}"), ("PATCH", f"{ADDRESSES}/{ids[2]}/default"),
                  ("DELETE", f"{ADDRESSES}/{ids[0]}")]
    for method, url in operations:
        assert audit.call(7, method, url).status_code == 200
        defaults = audit.default_ids(profile["id"])
        assert len(defaults) == 1
        assert audit.call(7, "GET", f"{ADDRESSES}/default").json()["id"] == defaults[0]


# === TC18-TC20: deactivation ===================================================================

def test_tc18_deactivate_profile(audit, two_customers):
    response = audit.call(7, "PATCH", f"{ACCOUNT}/deactivate")

    assert response.status_code == 200
    assert response.json()["profile_status"] == "DEACTIVATED"
    row = audit.profile_row(7)
    assert row.is_active is False and row.full_name == "Customer 7"
    assert audit.address_row(two_customers["victim_home"]["id"]) is not None


@pytest.mark.parametrize(("method", "path"), ADDRESS_ROUTES)
def test_tc19_inactive_profile_cannot_manage_addresses(audit, two_customers, method, path):
    own = two_customers["victim_office"]["id"]
    audit.call(7, "PATCH", f"{ACCOUNT}/deactivate")

    response = audit.call(7, method, fill(path, own), body_for(method, path))

    assert response.status_code == 403
    assert response.json() == DEACTIVATED
    row = audit.address_row(own)
    assert row is not None and row.address_line_1 == OFFICE["address_line_1"] and row.is_default is False
    assert audit.default_ids(two_customers["victim"]["id"]) == [two_customers["victim_home"]["id"]]


def test_tc20_user_service_does_not_change_the_authentication_account(audit, two_customers):
    before = audit.auth.snapshot()

    audit.call(7, "PATCH", f"{ACCOUNT}/deactivate")
    audit.call(8, "DELETE", PROFILE)
    after_deactivation = audit.call(7, "GET", PROFILE)

    assert audit.auth.snapshot() == before
    assert all(u["is_active"] for uid, u in audit.auth.users.items() if uid != 9)
    # The same token is still accepted by the Authentication Service; only the local profile is refused.
    assert audit.auth.verify(f"Bearer {audit.tokens[7]}")[0] == 200
    assert after_deactivation.status_code == 403 and after_deactivation.json() == DEACTIVATED
    # Every request the User Service ever sent was a read-only verify-token call with no body.
    assert {(r.method, r.url.path, r.content) for r in audit.auth.requests} == {("POST", VERIFY_PATH, b"")}


def test_tc20_no_code_path_can_call_any_other_authentication_endpoint():
    sources = {p: p.read_text(encoding="utf-8") for p in Path("app").rglob("*.py")}
    outbound = [(p, m.group(0)) for p, s in sources.items()
                for m in re.finditer(r"\.(post|get|put|patch|delete|request|send|stream)\(", s)
                if "client" in s[max(0, m.start() - 20):m.start()]]

    assert [(p.as_posix(), call) for p, call in outbound] == [("app/core/security.py", ".post(")]
    assert "auth_service_verify_url" in sources[Path("app/core/security.py")]


# === Security requirements across every endpoint ===============================================

def test_sr_route_inventory_is_what_the_audit_expects():
    # If a route is added, this fails, so the new route gets an explicit review.
    assert API_ROUTES == sorted([
        ("GET", ACCOUNT), ("PATCH", f"{ACCOUNT}/contact"), ("PATCH", f"{ACCOUNT}/deactivate"),
        ("POST", ADDRESSES), ("GET", ADDRESSES), ("GET", f"{ADDRESSES}/default"),
        ("GET", f"{ADDRESSES}/{{address_id}}"), ("PUT", f"{ADDRESSES}/{{address_id}}"),
        ("DELETE", f"{ADDRESSES}/{{address_id}}"), ("PATCH", f"{ADDRESSES}/{{address_id}}/default"),
        ("POST", PROFILE), ("GET", PROFILE), ("PUT", PROFILE), ("PATCH", PROFILE), ("DELETE", PROFILE),
    ])


@pytest.mark.parametrize(("method", "path"), API_ROUTES)
@pytest.mark.parametrize("auth", ["missing", "invalid", "expired"])
def test_sr_every_endpoint_returns_401_without_valid_authentication(audit, method, path, auth):
    audit.create_profile(7)
    audit.add_address(7)
    headers = {"missing": {}, "invalid": {"Authorization": "Bearer invalid.token.value"},
               "expired": {"Authorization": f"Bearer {audit.auth.issue_token(7, expires_in=-60)}"}}[auth]

    response = audit.call(None, method, fill(path), body_for(method, path), headers=headers)

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED
    assert audit.profile_row(7).is_active is True


@pytest.mark.parametrize(("method", "path"), API_ROUTES)
def test_sr_every_endpoint_returns_403_for_an_inactive_authentication_account(audit, method, path):
    response = audit.call(9, method, fill(path), body_for(method, path))

    assert response.status_code == 403
    assert response.json() == {"detail": "Inactive user"}


@pytest.mark.parametrize(("method", "path"), PROFILE_ROUTES)
def test_sr_every_endpoint_returns_403_for_a_deactivated_profile(audit, method, path):
    audit.create_profile(7)
    address = audit.add_address(7)
    audit.call(7, "DELETE", PROFILE)

    response = audit.call(7, method, fill(path, address["id"]), body_for(method, path))

    assert response.status_code == 403
    assert response.json() == DEACTIVATED


@pytest.mark.parametrize(("method", "path"), [r for r in ADDRESS_ROUTES if "{address_id}" in r[1]])
def test_sr_foreign_and_missing_addresses_are_indistinguishable(audit, two_customers, method, path):
    foreign = audit.call(8, method, fill(path, two_customers["victim_home"]["id"]), body_for(method, path))
    missing = audit.call(8, method, fill(path, 999999), body_for(method, path))

    assert foreign.status_code == missing.status_code == 404
    assert foreign.content == missing.content
    assert foreign.headers.get("content-type") == missing.headers.get("content-type")


def test_sr_openapi_has_no_password_secret_or_identity_input(audit):
    schema = audit.client.get("/openapi.json").json()
    for name, component in schema["components"]["schemas"].items():
        properties = set(component.get("properties", {}))
        assert not {p for p in properties if re.search("password|secret|token|hash", p)}, name
        if name.endswith(("Create", "Replace", "Update")):
            assert not properties & {"auth_user_id", "user_id", "id", "is_active", "role", "email"}, name
    for path, operations in schema["paths"].items():
        for operation in operations.values():
            names = {p["name"] for p in operation.get("parameters", [])}
            assert not names & {"auth_user_id", "user_id", "token", "access_token"}, path


def test_sr_no_password_or_secret_in_any_response(audit, two_customers):
    responses = [audit.call(7, m, fill(p, two_customers["victim_home"]["id"]), body_for(m, p))
                 for m, p in API_ROUTES if m == "GET"]
    for response in responses:
        assert response.status_code == 200
        assert not re.search("password|secret|hash", response.text, re.IGNORECASE)
        assert audit.tokens[7] not in response.text


def test_sr_tokens_never_appear_in_logs_or_responses(audit, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    expired = audit.auth.issue_token(7, expires_in=-1)
    inactive = audit.tokens[9]
    forged = sign_token({"sub": "7", "role": "ADMIN", "iat": 0, "exp": 4102444800}, key=b"other-key")
    texts = []

    audit.create_profile(7)
    audit.add_address(7)
    for token in (audit.tokens[7], expired, inactive, forged, "garbage-token-value-123"):
        for method, path in API_ROUTES:
            response = audit.call(None, method, fill(path), body_for(method, path),
                                  headers={"Authorization": f"Bearer {token}"})
            texts.append(response.text + str(response.headers))
    # Failure paths that log: database error and Authentication Service failure.
    monkeypatch.setattr(user_service, "get_active_profile",
                        lambda *a, **k: (_ for _ in ()).throw(OperationalError("SELECT", {}, Exception("x"))))
    texts.append(audit.call(7, "GET", PROFILE).text)
    monkeypatch.undo()

    def auth_service_down(_request):
        raise httpx.ConnectError("connection refused")
    app.dependency_overrides[get_auth_client] = lambda: httpx.Client(
        transport=httpx.MockTransport(auth_service_down))
    texts.append(audit.call(7, "GET", PROFILE).text)

    log_text = caplog.text + "".join(r.getMessage() for r in caplog.records)
    for token in (audit.tokens[7], expired, inactive, forged, "garbage-token-value-123"):
        assert token not in log_text
        assert token.split(".")[-1] not in log_text  # not even the signature part
        assert all(token not in t for t in texts)
    assert "Authorization" not in log_text and "Bearer" not in log_text


def _raise(exc):
    def raiser(*_args, **_kwargs):
        raise exc
    return raiser


@pytest.mark.parametrize(("exception", "status", "detail"), [
    (OperationalError("SELECT * FROM user_profiles WHERE auth_user_id = 7", {"p": "hunter2"},
                      Exception("(1045, \"Access denied for user 'shopease_user'@'172.18.0.3'\")")),
     503, "Service temporarily unavailable"),
    (RuntimeError("Traceback in /app/app/services/user_service.py line 42, MYSQL_PASSWORD=hunter2"),
     500, "Internal server error"),
    (KeyError("internal_cache_key_shopease_user_db"), 500, "Internal server error"),
])
def test_sr_internal_errors_return_no_details(audit, caplog, monkeypatch, exception, status, detail):
    audit.create_profile(7)
    monkeypatch.setattr(user_service, "get_active_profile", _raise(exception))

    response = audit.call(7, "GET", PROFILE)

    assert response.status_code == status
    assert response.json() == {"detail": detail}
    leaked = ("hunter2", "Access denied", "172.18", "SELECT", "Traceback", "/app/", "user_service.py",
              "shopease_user", "internal_cache_key")
    assert not [w for w in leaked if w in response.text]
    assert not [w for w in ("hunter2", "Access denied", "Traceback") if w in caplog.text]


@pytest.mark.parametrize(("auth_status", "auth_body"), [
    (500, "Traceback (most recent call last): File \"/app/auth.py\", SECRET_KEY=s3cr3t"),
    (502, "<html>Bad gateway at internal-lb-10.0.0.7</html>"),
    (200, '{"valid": true, "user": {"id": "seven", "debug": "SECRET_KEY=s3cr3t"}}'),
])
def test_sr_authentication_service_errors_are_not_passed_through(audit, caplog, auth_status, auth_body):
    app.dependency_overrides[get_auth_client] = lambda: httpx.Client(transport=httpx.MockTransport(
        lambda _r: httpx.Response(auth_status, text=auth_body)))

    response = audit.call(7, "GET", PROFILE)

    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication service unavailable"}
    for secret in ("s3cr3t", "Traceback", "10.0.0.7", "SECRET_KEY"):
        assert secret not in response.text and secret not in caplog.text


def test_sr_validation_errors_do_not_echo_input(audit):
    audit.create_profile(7)
    marker = "UNIQUE-MARKER-0123456789"

    responses = [
        audit.call(7, "PATCH", PROFILE, {"phone_number": marker}),
        audit.call(7, "POST", ADDRESSES, {**HOME, "postal_code": marker + "!"}),
        audit.call(7, "PATCH", PROFILE, {"gender": marker}),
        audit.call(7, "PATCH", PROFILE, {marker: 1}),
    ]
    for response in responses:
        assert response.status_code == 422
        assert marker not in response.text.replace(f'"field":"{marker}"', "")
