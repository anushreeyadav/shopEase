"""Tests for the account endpoints and GET /api/users/addresses/default.

Covers: account and profile retrieval, contact update, account deactivation (local profile
only, records kept, Authentication Service untouched), and the default delivery address,
including that no stale default remains after the default address is deleted.
"""

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import get_auth_client, get_current_authenticated_user
from app.main import app
from app.models import UserAddress, UserProfile

ACCOUNT = "/api/users/account"
PROFILE = "/api/users/profile"
ADDRESSES = "/api/users/addresses"
DEFAULT = f"{ADDRESSES}/default"

HOME = {
    "address_type": "HOME",
    "full_name": "Asha Rao",
    "phone_number": "+91 98765-43210",
    "address_line_1": "12 MG Road",
    "city": "Bengaluru",
    "state": "Karnataka",
    "country": "India",
    "postal_code": "560001",
}
OFFICE = {**HOME, "address_type": "OFFICE", "address_line_1": "1 Tech Park"}

NEW_ENDPOINTS = [
    ("GET", ACCOUNT, None),
    ("PATCH", f"{ACCOUNT}/contact", {"phone_number": "9876543210"}),
    ("PATCH", f"{ACCOUNT}/deactivate", None),
    ("GET", DEFAULT, None),
]

# Every operation a deactivated profile must be refused, across all three routers.
ALL_OPERATIONS = NEW_ENDPOINTS + [
    ("POST", PROFILE, {"full_name": "Asha"}),
    ("GET", PROFILE, None),
    ("PUT", PROFILE, {"full_name": "Asha"}),
    ("PATCH", PROFILE, {"full_name": "Asha"}),
    ("DELETE", PROFILE, None),
    ("POST", ADDRESSES, HOME),
    ("GET", ADDRESSES, None),
    ("GET", f"{ADDRESSES}/{{id}}", None),
    ("PUT", f"{ADDRESSES}/{{id}}", HOME),
    ("DELETE", f"{ADDRESSES}/{{id}}", None),
    ("PATCH", f"{ADDRESSES}/{{id}}/default", None),
]


def create_profile(client: TestClient, **fields) -> dict:
    response = client.post(PROFILE, json={"full_name": "Asha Rao", **fields})
    assert response.status_code == 201
    return response.json()


def add(client: TestClient, body: dict = HOME, **changes) -> dict:
    response = client.post(ADDRESSES, json={**body, **changes})
    assert response.status_code == 201, response.text
    return response.json()


def stored_profile(db_session, auth_user_id: int) -> UserProfile:
    db_session.expire_all()
    return db_session.scalars(select(UserProfile).where(UserProfile.auth_user_id == auth_user_id)).one()


def default_ids(db_session, profile_id: int) -> list[int]:
    db_session.expire_all()
    return list(db_session.scalars(
        select(UserAddress.id).where(UserAddress.user_id == profile_id, UserAddress.is_default.is_(True))))


@pytest.fixture
def owner(api) -> tuple[TestClient, dict]:
    client, _ = api
    return client, create_profile(client, phone_number="+44 20 7946 0958")


# --- Authentication is required ----------------------------------------------------------------

@pytest.mark.parametrize(("method", "url", "body"), NEW_ENDPOINTS)
def test_new_endpoints_reject_a_missing_token(method, url, body):
    calls = []
    app.dependency_overrides[get_auth_client] = lambda: httpx.Client(
        transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200)))
    try:
        response = TestClient(app).request(method, url, json=body)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
    assert calls == []


@pytest.mark.parametrize(("method", "url", "body"), NEW_ENDPOINTS)
def test_new_endpoints_reject_a_token_the_auth_service_rejects(method, url, body):
    app.dependency_overrides[get_auth_client] = lambda: httpx.Client(transport=httpx.MockTransport(
        lambda _r: httpx.Response(401, json={"detail": "Could not validate credentials"})))
    try:
        response = TestClient(app).request(method, url, json=body,
                                           headers={"Authorization": "Bearer expired.or.invalid"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


def test_inactive_authentication_account_is_rejected_before_the_profile_is_read(api, db_session):
    client, _ = api
    create_profile(client)
    app.dependency_overrides.pop(get_current_authenticated_user)  # use the real verification
    app.dependency_overrides[get_auth_client] = lambda: httpx.Client(transport=httpx.MockTransport(
        lambda _r: httpx.Response(403, json={"detail": "Inactive user"})))

    response = client.get(ACCOUNT, headers={"Authorization": "Bearer token.of.inactive.user"})

    assert response.status_code == 403
    assert response.json() == {"detail": "Inactive user"}
    assert stored_profile(db_session, 7).is_active is True  # the local profile is not changed


# --- GET /api/users/account --------------------------------------------------------------------

def test_account_with_a_profile(owner):
    client, profile = owner

    response = client.get(ACCOUNT)

    assert response.status_code == 200
    assert response.json() == {
        "authentication_account": {"auth_user_id": 7, "full_name": "User 7", "email": "user7@example.com",
                                   "role": "USER", "status": "ACTIVE"},
        "profile_status": "ACTIVE",
        "profile": profile,
    }


def test_account_before_a_profile_exists(api):
    client, _ = api

    response = client.get(ACCOUNT)

    assert response.status_code == 200
    body = response.json()
    assert body["authentication_account"]["auth_user_id"] == 7
    assert body["profile_status"] == "NOT_CREATED"
    assert body["profile"] is None


def test_account_shows_only_the_callers_data(api):
    client, auth_as = api
    create_profile(client)
    auth_as(8)
    create_profile(client, full_name="Ravi Kumar")

    body = client.get(ACCOUNT, params={"auth_user_id": 7}).json()

    assert body["authentication_account"]["auth_user_id"] == 8
    assert body["profile"]["auth_user_id"] == 8
    assert body["profile"]["full_name"] == "Ravi Kumar"


# --- PATCH /api/users/account/contact ----------------------------------------------------------

def test_update_contact_phone(owner, db_session):
    client, profile = owner

    response = client.patch(f"{ACCOUNT}/contact", json={"phone_number": "0091 98765 43210"})

    assert response.status_code == 200
    body = response.json()
    assert body["phone_number"] == "+919876543210"
    assert {k: v for k, v in body.items() if k not in ("phone_number", "updated_at")} == {
        k: v for k, v in profile.items() if k not in ("phone_number", "updated_at")}
    assert stored_profile(db_session, 7).phone_number == "+919876543210"


def test_contact_phone_can_be_cleared(owner, db_session):
    client, _ = owner

    response = client.patch(f"{ACCOUNT}/contact", json={"phone_number": None})

    assert response.status_code == 200
    assert response.json()["phone_number"] is None
    assert stored_profile(db_session, 7).phone_number is None


@pytest.mark.parametrize(("body", "field"), [
    ({}, "phone_number"),
    ({"phone_number": "12345"}, "phone_number"),
    ({"phone_number": "call me"}, "phone_number"),
    ({"phone_number": "9876543210", "email": "new@example.com"}, "email"),
    ({"phone_number": "9876543210", "full_name": "Other"}, "full_name"),
    ({"phone_number": "9876543210", "auth_user_id": 8}, "auth_user_id"),
])
def test_invalid_contact_updates_are_rejected(owner, db_session, body, field):
    client, _ = owner

    response = client.patch(f"{ACCOUNT}/contact", json=body)

    assert response.status_code == 422
    assert [e["field"] for e in response.json()["errors"]] == [field]
    assert stored_profile(db_session, 7).phone_number == "+442079460958"


def test_contact_update_without_a_profile(api):
    client, _ = api

    response = client.patch(f"{ACCOUNT}/contact", json={"phone_number": "9876543210"})

    assert response.status_code == 404
    assert response.json() == {"detail": "User profile not found"}


def test_contact_update_only_changes_the_caller(api, db_session):
    client, auth_as = api
    create_profile(client, phone_number="9876543210")
    auth_as(8)
    create_profile(client, phone_number="9123456789")

    client.patch(f"{ACCOUNT}/contact", json={"phone_number": "9000000000"})

    assert stored_profile(db_session, 7).phone_number == "9876543210"
    assert stored_profile(db_session, 8).phone_number == "9000000000"


# --- PATCH /api/users/account/deactivate -------------------------------------------------------

def test_deactivate_account(owner, db_session):
    client, profile = owner

    response = client.patch(f"{ACCOUNT}/deactivate")

    assert response.status_code == 200
    assert response.json() == {"message": "User profile deactivated", "profile_status": "DEACTIVATED",
                               "authentication_account_changed": False}
    stored = stored_profile(db_session, 7)
    assert stored.id == profile["id"]
    assert stored.is_active is False
    assert stored.full_name == "Asha Rao" and stored.phone_number == "+442079460958"


def test_deactivation_preserves_addresses_and_the_default(owner, db_session):
    client, profile = owner
    first = add(client)
    second = add(client, OFFICE, is_default=True)

    client.patch(f"{ACCOUNT}/deactivate")

    db_session.expire_all()
    kept = db_session.scalars(select(UserAddress).where(UserAddress.user_id == profile["id"])).all()
    assert sorted(a.id for a in kept) == [first["id"], second["id"]]
    assert default_ids(db_session, profile["id"]) == [second["id"]]


def test_deactivation_does_not_call_the_authentication_service(owner):
    client, _ = owner
    calls = []
    app.dependency_overrides[get_auth_client] = lambda: httpx.Client(
        transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(500)))

    response = client.patch(f"{ACCOUNT}/deactivate")

    # The caller is set directly in these tests, so any request here would be the account code
    # trying to change or delete the Authentication Service account.
    assert response.status_code == 200
    assert calls == []


def test_deactivate_without_a_profile(api):
    client, _ = api

    response = client.patch(f"{ACCOUNT}/deactivate")

    assert response.status_code == 404
    assert response.json() == {"detail": "User profile not found"}


def test_deactivating_twice(owner):
    client, _ = owner
    client.patch(f"{ACCOUNT}/deactivate")

    response = client.patch(f"{ACCOUNT}/deactivate")

    assert response.status_code == 403
    assert response.json() == {"detail": "User profile is deactivated"}


@pytest.mark.parametrize("deactivate", [("PATCH", f"{ACCOUNT}/deactivate"), ("DELETE", PROFILE)],
                         ids=["account-deactivate", "profile-delete"])
@pytest.mark.parametrize(("method", "url", "body"), ALL_OPERATIONS)
def test_inactive_profile_cannot_do_anything(owner, db_session, deactivate, method, url, body):
    client, profile = owner
    address = add(client)
    assert client.request(*deactivate).status_code == 200

    response = client.request(method, url.format(id=address["id"]), json=body)

    assert response.status_code == 403
    assert response.json() == {"detail": "User profile is deactivated"}
    stored = stored_profile(db_session, 7)
    assert stored.is_active is False and stored.full_name == "Asha Rao"
    assert db_session.get(UserAddress, address["id"]).address_line_1 == HOME["address_line_1"]


def test_deactivation_does_not_affect_other_users(api):
    client, auth_as = api
    create_profile(client)
    add(client)
    auth_as(8)
    create_profile(client)
    client.patch(f"{ACCOUNT}/deactivate")

    auth_as(7)
    assert client.get(ACCOUNT).json()["profile_status"] == "ACTIVE"
    assert client.get(DEFAULT).status_code == 200


# --- GET /api/users/addresses/default ----------------------------------------------------------

def test_get_default_address(owner):
    client, _ = owner
    first = add(client)
    add(client, OFFICE)

    response = client.get(DEFAULT)

    assert response.status_code == 200
    assert response.json() == first


def test_default_address_follows_a_change_of_default(owner):
    client, _ = owner
    add(client)
    second = add(client, OFFICE)

    client.patch(f"{ADDRESSES}/{second['id']}/default")

    assert client.get(DEFAULT).json()["id"] == second["id"]


def test_default_address_when_there_are_no_addresses(owner):
    client, _ = owner

    response = client.get(DEFAULT)

    assert response.status_code == 404
    assert response.json() == {"detail": "Default address not found"}


def test_default_address_without_a_profile(api):
    client, _ = api

    response = client.get(DEFAULT)

    assert response.status_code == 404
    assert response.json() == {"detail": "User profile not found"}


def test_default_address_is_never_another_users(api):
    client, auth_as = api
    create_profile(client)
    auth_as(8)
    create_profile(client)
    add(client, OFFICE)

    auth_as(7)
    assert client.get(DEFAULT).status_code == 404
    mine = add(client)
    assert client.get(DEFAULT).json()["id"] == mine["id"]


def test_default_is_not_treated_as_an_address_id(owner):
    client, _ = owner
    add(client)

    response = client.get(DEFAULT)

    assert response.status_code == 200  # not 422 from the /{address_id} route


# --- No stale default after deleting the default address ---------------------------------------

def test_deleting_the_default_leaves_no_stale_default(owner, db_session):
    client, profile = owner
    oldest = add(client)
    add(client, OFFICE)
    newest = add(client, OFFICE, address_type="OTHER", is_default=True)

    client.delete(f"{ADDRESSES}/{newest['id']}")

    default = client.get(DEFAULT).json()
    assert default["id"] == oldest["id"]  # the documented promotion: the oldest remaining address
    assert default_ids(db_session, profile["id"]) == [oldest["id"]]
    assert newest["id"] not in [a["id"] for a in client.get(ADDRESSES).json()]


def test_deleting_the_only_address_leaves_no_default(owner, db_session):
    client, profile = owner
    only = add(client)

    client.delete(f"{ADDRESSES}/{only['id']}")

    assert client.get(DEFAULT).status_code == 404
    assert default_ids(db_session, profile["id"]) == []
    db_session.expire_all()
    assert db_session.get(UserAddress, only["id"]) is None


def test_deleting_a_non_default_address_keeps_the_default(owner):
    client, _ = owner
    first = add(client)
    second = add(client, OFFICE)

    client.delete(f"{ADDRESSES}/{second['id']}")

    assert client.get(DEFAULT).json()["id"] == first["id"]
