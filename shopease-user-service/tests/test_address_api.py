"""Tests for every /api/users/addresses endpoint: ownership, validation, default rules, transactions.

Authentication itself is covered by test_auth_integration.py. Here the verified caller is
set directly, except in the tests that check every endpoint demands a token.
"""

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.core.security import get_auth_client
from app.main import app
from app.models import UserAddress, UserProfile
from app.services import address_service

URL = "/api/users/addresses"

HOME = {
    "address_type": "HOME",
    "full_name": "Asha Rao",
    "phone_number": "+91 98765-43210",
    "address_line_1": "12 MG Road",
    "address_line_2": "Flat 4B",
    "city": "Bengaluru",
    "state": "Karnataka",
    "country": "India",
    "postal_code": "560001",
}
OFFICE = {**HOME, "address_type": "OFFICE", "address_line_1": "1 Tech Park", "address_line_2": None,
          "postal_code": "560103"}

ENDPOINTS = [
    ("POST", URL, HOME),
    ("GET", URL, None),
    ("GET", f"{URL}/1", None),
    ("PUT", f"{URL}/1", HOME),
    ("DELETE", f"{URL}/1", None),
    ("PATCH", f"{URL}/1/default", None),
]


def create_profile(client: TestClient, name: str = "Asha Rao") -> dict:
    response = client.post("/api/users/profile", json={"full_name": name})
    assert response.status_code == 201
    return response.json()


def add(client: TestClient, body: dict | None = None, **changes) -> dict:
    response = client.post(URL, json={**(body or HOME), **changes})
    assert response.status_code == 201, response.text
    return response.json()


def defaults_of(db_session, profile_id: int) -> list[int]:
    return list(db_session.scalars(
        select(UserAddress.id).where(UserAddress.user_id == profile_id, UserAddress.is_default.is_(True))
    ))


def address_ids_of(db_session, profile_id: int) -> list[int]:
    # Scoped to one profile: with USER_SERVICE_TEST_DB=mysql the table may hold other rows.
    db_session.expire_all()
    return list(db_session.scalars(select(UserAddress.id).where(UserAddress.user_id == profile_id)))


def address_exists(db_session, address_id: int) -> bool:
    db_session.expire_all()
    return db_session.get(UserAddress, address_id) is not None


@pytest.fixture
def owner(api) -> tuple[TestClient, dict]:
    """User 7 with a profile."""
    client, _ = api
    return client, create_profile(client)


@pytest.fixture
def stranger_address(api, owner) -> dict:
    """An address that belongs to user 8. Leaves the caller set to user 7 (owner)."""
    client, auth_as = api
    auth_as(8)
    create_profile(client, "Other Person")
    address = add(client, OFFICE)
    auth_as(7)
    return address


# --- Authentication and profile are required on every endpoint ---------------------------------

@pytest.mark.parametrize(("method", "url", "body"), ENDPOINTS)
def test_every_endpoint_rejects_a_missing_token(method, url, body):
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


@pytest.mark.parametrize(("method", "url", "body"), ENDPOINTS)
def test_every_endpoint_rejects_a_token_the_auth_service_rejects(method, url, body):
    app.dependency_overrides[get_auth_client] = lambda: httpx.Client(transport=httpx.MockTransport(
        lambda _r: httpx.Response(401, json={"detail": "Could not validate credentials"})))
    try:
        response = TestClient(app).request(method, url, json=body,
                                           headers={"Authorization": "Bearer expired.or.invalid"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


@pytest.mark.parametrize(("method", "url", "body"), ENDPOINTS)
def test_every_endpoint_needs_a_profile(api, method, url, body):
    client, _ = api

    response = client.request(method, url, json=body)

    assert response.status_code == 404
    assert response.json() == {"detail": "User profile not found"}


@pytest.mark.parametrize(("method", "url", "body"), ENDPOINTS)
def test_every_endpoint_rejects_a_deactivated_profile(owner, db_session, method, url, body):
    client, profile = owner
    add(client)  # address 1 may exist; the profile check comes first either way
    assert client.delete("/api/users/profile").status_code == 200
    before = address_ids_of(db_session, profile["id"])

    response = client.request(method, url, json=body)

    assert response.status_code == 403
    assert response.json() == {"detail": "User profile is deactivated"}
    assert address_ids_of(db_session, profile["id"]) == before


# --- POST: add ---------------------------------------------------------------------------------

def test_create_address(owner):
    client, profile = owner

    response = client.post(URL, json=HOME)

    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == profile["id"]
    assert body["phone_number"] == "+919876543210"
    assert body["address_line_2"] == "Flat 4B"
    assert {k: body[k] for k in ("address_type", "full_name", "city", "state", "country", "postal_code")} == {
        k: HOME[k] for k in ("address_type", "full_name", "city", "state", "country", "postal_code")}
    assert body["is_default"] is True  # the first address
    assert body["id"] >= 1 and body["created_at"]


def test_second_address_is_not_default_unless_asked(owner, db_session):
    client, profile = owner
    first = add(client)

    second = add(client, OFFICE)

    assert second["is_default"] is False
    assert defaults_of(db_session, profile["id"]) == [first["id"]]


def test_creating_a_default_address_replaces_the_old_default(owner, db_session):
    client, profile = owner
    first = add(client)

    second = add(client, OFFICE, is_default=True)

    assert second["is_default"] is True
    assert defaults_of(db_session, profile["id"]) == [second["id"]]
    assert client.get(f"{URL}/{first['id']}").json()["is_default"] is False


def test_first_address_is_default_even_if_is_default_false(owner):
    client, _ = owner
    assert add(client, is_default=False)["is_default"] is True


def test_optional_fields_can_be_left_out(owner):
    client, _ = owner
    body = {k: v for k, v in HOME.items() if k not in ("address_type", "address_line_2")}

    created = add(client, body)

    assert created["address_type"] == "HOME"
    assert created["address_line_2"] is None


@pytest.mark.parametrize("address_type", ["HOME", "OFFICE", "OTHER"])
def test_every_address_type_is_accepted(owner, address_type):
    client, _ = owner
    assert add(client, address_type=address_type)["address_type"] == address_type


@pytest.mark.parametrize("field", ["user_id", "auth_user_id", "id", "created_at", "default_marker"])
def test_owner_and_server_fields_cannot_be_sent(owner, db_session, field):
    client, profile = owner

    response = client.post(URL, json={**HOME, field: 8})

    assert response.status_code == 422
    assert response.json()["errors"] == [{"field": field, "message": "Extra inputs are not permitted"}]
    assert address_ids_of(db_session, profile["id"]) == []


@pytest.mark.parametrize("field", ["full_name", "phone_number", "address_line_1", "city", "state", "country",
                                   "postal_code"])
def test_required_fields(owner, field):
    client, _ = owner
    body = {k: v for k, v in HOME.items() if k != field}

    response = client.post(URL, json=body)

    assert response.status_code == 422
    assert response.json()["detail"] == "Validation failed"
    assert [e["field"] for e in response.json()["errors"]] == [field]


@pytest.mark.parametrize(("field", "value"), [
    ("address_type", "WORK"),
    ("address_type", "home"),
    ("address_type", "Office"),
    ("address_type", None),
    ("full_name", ""),
    ("full_name", "   "),
    ("full_name", None),
    ("full_name", "A" * 256),
    ("full_name", "Asha\nRao"),
    ("phone_number", "12345"),
    ("phone_number", "not a phone"),
    ("phone_number", None),
    ("address_line_1", ""),
    ("address_line_1", "x" * 256),
    ("address_line_1", "12 MG Road\r\nInjected"),
    ("address_line_2", ""),
    ("address_line_2", "x" * 256),
    ("city", ""),
    ("city", "x" * 101),
    ("state", "   "),
    ("country", ""),
    ("country", None),
    ("postal_code", "56"),
    ("postal_code", "560 001!"),
    ("postal_code", "-560001"),
    ("postal_code", "x" * 21),
    ("postal_code", 560001),
    ("is_default", "maybe"),
])
def test_invalid_values_are_rejected(owner, db_session, field, value):
    client, profile = owner

    response = client.post(URL, json={**HOME, field: value})

    assert response.status_code == 422
    errors = response.json()["errors"]
    assert [e["field"] for e in errors] == [field]
    if isinstance(value, str) and len(value) > 3:
        assert value not in errors[0]["message"]  # input is not echoed
    assert address_ids_of(db_session, profile["id"]) == []


@pytest.mark.parametrize(("field", "value", "stored"), [
    ("postal_code", "SW1A 1AA", "SW1A 1AA"),
    ("postal_code", "94105-1804", "94105-1804"),
    ("postal_code", "  560001  ", "560001"),
    ("city", "  Bengaluru ", "Bengaluru"),
    ("phone_number", "080 2345 6789", "08023456789"),
    ("full_name", "A" * 255, "A" * 255),
    ("address_line_1", "x" * 255, "x" * 255),
])
def test_valid_values_are_normalized(owner, field, value, stored):
    client, _ = owner
    assert add(client, **{field: value})[field] == stored


# --- GET: list and read ------------------------------------------------------------------------

def test_list_is_empty_for_a_new_profile(owner):
    client, _ = owner

    response = client.get(URL)

    assert response.status_code == 200
    assert response.json() == []


def test_list_puts_the_default_first(owner):
    client, _ = owner
    first = add(client)
    second = add(client, OFFICE)
    third = add(client, OFFICE, address_type="OTHER", is_default=True)

    response = client.get(URL)

    assert response.status_code == 200
    assert [a["id"] for a in response.json()] == [third["id"], first["id"], second["id"]]
    assert [a["is_default"] for a in response.json()] == [True, False, False]


def test_list_shows_only_the_callers_addresses(owner, stranger_address):
    client, _ = owner
    mine = add(client)

    assert [a["id"] for a in client.get(URL).json()] == [mine["id"]]


def test_read_address(owner):
    client, _ = owner
    created = add(client)

    response = client.get(f"{URL}/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_read_missing_address(owner):
    client, _ = owner

    response = client.get(f"{URL}/999999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Address not found"}


@pytest.mark.parametrize("address_id", ["0", "-1", "abc", "1.5", "2147483648"])
def test_invalid_address_id(owner, address_id):
    client, _ = owner

    response = client.get(f"{URL}/{address_id}")

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "address_id"


# --- Ownership: another user's address is never reachable --------------------------------------

def test_another_users_address_looks_exactly_like_a_missing_one(owner, stranger_address):
    client, _ = owner

    theirs = client.get(f"{URL}/{stranger_address['id']}")
    missing = client.get(f"{URL}/999999")

    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json() == {"detail": "Address not found"}


def test_cannot_replace_another_users_address(owner, stranger_address, db_session):
    client, _ = owner

    response = client.put(f"{URL}/{stranger_address['id']}", json=HOME)

    assert response.status_code == 404
    db_session.expire_all()
    assert db_session.get(UserAddress, stranger_address["id"]).address_line_1 == OFFICE["address_line_1"]


def test_cannot_delete_another_users_address(owner, stranger_address, db_session):
    client, _ = owner

    response = client.delete(f"{URL}/{stranger_address['id']}")

    assert response.status_code == 404
    assert address_exists(db_session, stranger_address["id"])


def test_cannot_make_another_users_address_my_default(owner, stranger_address, db_session):
    client, profile = owner
    mine = add(client)

    response = client.patch(f"{URL}/{stranger_address['id']}/default")

    assert response.status_code == 404
    assert defaults_of(db_session, profile["id"]) == [mine["id"]]
    assert defaults_of(db_session, stranger_address["user_id"]) == [stranger_address["id"]]


def test_owner_comes_from_the_token_not_the_query(owner, stranger_address):
    client, profile = owner

    created = client.post(URL, json=HOME, params={"user_id": stranger_address["user_id"], "auth_user_id": 8})

    assert created.status_code == 201
    assert created.json()["user_id"] == profile["id"]


# --- PUT: replace ------------------------------------------------------------------------------

def test_replace_address(owner):
    client, _ = owner
    created = add(client)
    new = {**OFFICE, "city": "Mysuru", "phone_number": "0821 234 5678"}

    response = client.put(f"{URL}/{created['id']}", json=new)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"] and body["created_at"] == created["created_at"]
    assert body["city"] == "Mysuru"
    assert body["address_type"] == "OFFICE"
    assert body["phone_number"] == "08212345678"
    assert body["is_default"] is True  # unchanged
    assert client.get(f"{URL}/{created['id']}").json() == body


def test_replace_sets_omitted_optional_fields_to_their_defaults(owner):
    client, _ = owner
    created = add(client, address_type="OTHER")
    body = {k: v for k, v in HOME.items() if k not in ("address_type", "address_line_2")}

    response = client.put(f"{URL}/{created['id']}", json=body)

    assert response.status_code == 200
    assert response.json()["address_line_2"] is None
    assert response.json()["address_type"] == "HOME"


def test_replace_keeps_a_non_default_address_non_default(owner, db_session):
    client, profile = owner
    first = add(client)
    second = add(client, OFFICE)

    assert client.put(f"{URL}/{second['id']}", json=HOME).json()["is_default"] is False
    assert defaults_of(db_session, profile["id"]) == [first["id"]]


@pytest.mark.parametrize("field", ["is_default", "user_id", "auth_user_id", "id"])
def test_replace_rejects_fields_it_cannot_change(owner, field):
    client, _ = owner
    created = add(client)

    response = client.put(f"{URL}/{created['id']}", json={**HOME, field: True})

    assert response.status_code == 422
    assert [e["field"] for e in response.json()["errors"]] == [field]


@pytest.mark.parametrize(("field", "value"), [("city", ""), ("postal_code", "!!"), ("full_name", None)])
def test_replace_validates_like_create(owner, field, value):
    client, _ = owner
    created = add(client)

    response = client.put(f"{URL}/{created['id']}", json={**HOME, field: value})

    assert response.status_code == 422
    assert client.get(f"{URL}/{created['id']}").json() == created


def test_replace_requires_the_required_fields(owner):
    client, _ = owner
    created = add(client)

    response = client.put(f"{URL}/{created['id']}", json={"city": "Mysuru"})

    assert response.status_code == 422
    assert {e["field"] for e in response.json()["errors"]} == {
        "full_name", "phone_number", "address_line_1", "state", "country", "postal_code"}


def test_replace_missing_address(owner):
    client, _ = owner
    assert client.put(f"{URL}/999999", json=HOME).status_code == 404


# --- DELETE ------------------------------------------------------------------------------------

def test_delete_address(owner, db_session):
    client, profile = owner
    first = add(client)
    second = add(client, OFFICE)

    response = client.delete(f"{URL}/{second['id']}")

    assert response.status_code == 200
    assert response.json() == {"message": "Address deleted"}
    assert not address_exists(db_session, second["id"])
    assert client.get(f"{URL}/{second['id']}").status_code == 404
    assert defaults_of(db_session, profile["id"]) == [first["id"]]


def test_deleting_the_default_makes_the_oldest_remaining_address_default(owner, db_session):
    client, profile = owner
    oldest = add(client)
    middle = add(client, OFFICE)
    newest = add(client, OFFICE, is_default=True)

    assert client.delete(f"{URL}/{newest['id']}").status_code == 200

    assert defaults_of(db_session, profile["id"]) == [oldest["id"]]
    assert client.get(f"{URL}/{middle['id']}").json()["is_default"] is False


def test_deleting_the_last_address_leaves_no_default(owner, db_session):
    client, profile = owner
    only = add(client)

    assert client.delete(f"{URL}/{only['id']}").status_code == 200
    assert client.get(URL).json() == []
    assert defaults_of(db_session, profile["id"]) == []
    assert add(client, OFFICE)["is_default"] is True  # the next address becomes the default again


def test_delete_twice(owner):
    client, _ = owner
    created = add(client)

    assert client.delete(f"{URL}/{created['id']}").status_code == 200
    second = client.delete(f"{URL}/{created['id']}")

    assert second.status_code == 404
    assert second.json() == {"detail": "Address not found"}


def test_deleting_an_address_keeps_the_profile(owner, db_session):
    client, profile = owner
    created = add(client)

    client.delete(f"{URL}/{created['id']}")

    assert client.get("/api/users/profile").status_code == 200
    assert db_session.get(UserProfile, profile["id"]) is not None


# --- PATCH .../default -------------------------------------------------------------------------

def test_set_default_address(owner, db_session):
    client, profile = owner
    first = add(client)
    second = add(client, OFFICE)

    response = client.patch(f"{URL}/{second['id']}/default")

    assert response.status_code == 200
    assert response.json()["id"] == second["id"]
    assert response.json()["is_default"] is True
    assert defaults_of(db_session, profile["id"]) == [second["id"]]
    assert client.get(f"{URL}/{first['id']}").json()["is_default"] is False


def test_set_default_on_the_current_default_changes_nothing(owner, db_session):
    client, profile = owner
    first = add(client)
    add(client, OFFICE)

    response = client.patch(f"{URL}/{first['id']}/default")

    assert response.status_code == 200
    assert response.json()["is_default"] is True
    assert defaults_of(db_session, profile["id"]) == [first["id"]]


def test_switching_default_repeatedly_always_leaves_exactly_one(owner, db_session):
    client, profile = owner
    ids = [add(client)["id"], add(client, OFFICE)["id"], add(client, OFFICE, address_type="OTHER")["id"]]

    for address_id in ids + ids[::-1]:
        assert client.patch(f"{URL}/{address_id}/default").status_code == 200
        assert defaults_of(db_session, profile["id"]) == [address_id]


def test_set_default_does_not_change_other_users_default(owner, stranger_address, db_session):
    client, _ = owner
    add(client)
    mine = add(client, OFFICE)

    client.patch(f"{URL}/{mine['id']}/default")

    assert defaults_of(db_session, stranger_address["user_id"]) == [stranger_address["id"]]


def test_set_default_missing_address(owner):
    client, _ = owner

    response = client.patch(f"{URL}/999999/default")

    assert response.status_code == 404
    assert response.json() == {"detail": "Address not found"}


# --- Transactions: profile lock and rollback ---------------------------------------------------

@pytest.mark.parametrize(("method", "path", "body", "locks"), [
    ("POST", "", HOME, True),
    ("PUT", "/{id}", HOME, True),
    ("DELETE", "/{id}", None, True),
    ("PATCH", "/{id}/default", None, True),
    ("GET", "", None, False),
    ("GET", "/{id}", None, False),
])
def test_writes_lock_the_owning_profile_row(owner, monkeypatch, method, path, body, locks):
    client, _ = owner
    address = add(client)
    calls = []
    real = address_service.get_active_profile

    def recording(db, auth_user_id, *, for_update=False):
        calls.append((auth_user_id, for_update))
        return real(db, auth_user_id, for_update=for_update)

    monkeypatch.setattr(address_service, "get_active_profile", recording)

    response = client.request(method, URL + path.format(id=address["id"]), json=body)

    assert response.status_code < 300
    assert calls == [(7, locks)]


def _fail_commit(monkeypatch, db_session):
    def failing_commit():
        raise OperationalError("COMMIT", {}, Exception("connection lost"))
    monkeypatch.setattr(db_session, "commit", failing_commit)


def test_failed_set_default_rolls_back_clearing_the_old_default(owner, db_session, monkeypatch):
    client, profile = owner
    first = add(client)
    second = add(client, OFFICE)
    _fail_commit(monkeypatch, db_session)

    response = client.patch(f"{URL}/{second['id']}/default")

    assert response.status_code == 503
    assert response.json() == {"detail": "Service temporarily unavailable"}
    monkeypatch.undo()
    db_session.expire_all()
    assert defaults_of(db_session, profile["id"]) == [first["id"]]


def test_failed_create_rolls_back_everything(owner, db_session, monkeypatch):
    client, profile = owner
    first = add(client)
    _fail_commit(monkeypatch, db_session)

    response = client.post(URL, json={**OFFICE, "is_default": True})

    assert response.status_code == 503
    monkeypatch.undo()
    db_session.expire_all()
    assert [a["id"] for a in client.get(URL).json()] == [first["id"]]
    assert defaults_of(db_session, profile["id"]) == [first["id"]]


def test_failed_delete_rolls_back_the_delete_and_the_promotion(owner, db_session, monkeypatch):
    client, profile = owner
    first = add(client)
    second = add(client, OFFICE)
    _fail_commit(monkeypatch, db_session)

    response = client.delete(f"{URL}/{first['id']}")

    assert response.status_code == 503
    monkeypatch.undo()
    db_session.expire_all()
    assert {a["id"] for a in client.get(URL).json()} == {first["id"], second["id"]}
    assert defaults_of(db_session, profile["id"]) == [first["id"]]
