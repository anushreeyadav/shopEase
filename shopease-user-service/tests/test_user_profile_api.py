"""Tests for every /api/users/profile endpoint: identity, validation, deactivation, responses.

Authentication itself is covered by test_auth_integration.py. Here the verified caller is
set directly, except in the tests that check every endpoint demands a token.
"""

from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import get_auth_client
from app.main import app
from app.models import UserProfile
from app.schemas.user_schema import UserProfileCreate
from app.services import user_service

URL = "/api/users/profile"

FULL_PROFILE = {
    "full_name": "Asha Rao",
    "phone_number": "+91 98765-43210",
    "date_of_birth": "1995-04-12",
    "gender": "FEMALE",
    "profile_image": "https://cdn.example.com/avatars/7.png",
}

ENDPOINTS = [("POST", FULL_PROFILE), ("GET", None), ("PUT", FULL_PROFILE), ("PATCH", {"full_name": "X"}), ("DELETE", None)]


def call(client: TestClient, method: str, body: dict | None = None, **kwargs) -> httpx.Response:
    return client.request(method, URL, json=body, **kwargs)


def stored_profile(db_session, auth_user_id: int) -> UserProfile | None:
    return db_session.scalars(select(UserProfile).where(UserProfile.auth_user_id == auth_user_id)).one_or_none()


# --- Authentication is required on every endpoint ---------------------------------------------

@pytest.mark.parametrize(("method", "body"), ENDPOINTS)
def test_every_endpoint_rejects_a_missing_token(method, body):
    calls = []
    app.dependency_overrides[get_auth_client] = lambda: httpx.Client(
        transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200)))
    try:
        response = call(TestClient(app), method, body)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
    assert calls == []


@pytest.mark.parametrize(("method", "body"), ENDPOINTS)
def test_every_endpoint_rejects_a_token_the_auth_service_rejects(method, body):
    app.dependency_overrides[get_auth_client] = lambda: httpx.Client(transport=httpx.MockTransport(
        lambda _r: httpx.Response(401, json={"detail": "Could not validate credentials"})))
    try:
        response = call(TestClient(app), method, body, headers={"Authorization": "Bearer expired.or.invalid"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


# --- POST: create ------------------------------------------------------------------------------

def test_create_profile(api, db_session):
    client, _ = api

    response = call(client, "POST", FULL_PROFILE)

    assert response.status_code == 201
    body = response.json()
    assert body["auth_user_id"] == 7
    assert body["full_name"] == "Asha Rao"
    assert body["phone_number"] == "+919876543210"
    assert body["date_of_birth"] == "1995-04-12"
    assert body["gender"] == "FEMALE"
    assert body["profile_image"] == "https://cdn.example.com/avatars/7.png"
    assert body["is_active"] is True
    assert body["created_at"] and body["updated_at"]
    assert set(body) == {"id", "auth_user_id", "full_name", "phone_number", "date_of_birth", "gender",
                         "profile_image", "is_active", "created_at", "updated_at"}
    assert stored_profile(db_session, 7).id == body["id"]


def test_create_profile_with_only_full_name(api):
    client, _ = api

    body = call(client, "POST", {"full_name": "  Asha Rao  "}).json()

    assert body["full_name"] == "Asha Rao"
    assert [body[f] for f in ("phone_number", "date_of_birth", "gender", "profile_image")] == [None] * 4


def test_duplicate_profile_is_rejected(api):
    client, _ = api
    call(client, "POST", FULL_PROFILE)

    response = call(client, "POST", {"full_name": "Second"})

    assert response.status_code == 409
    assert response.json() == {"detail": "User profile already exists"}


def test_duplicate_created_concurrently_is_reported_as_409(api, db_session, monkeypatch):
    # Simulates another request inserting between the existence check and this insert:
    # the check sees nothing, and the unique constraint on auth_user_id stops the duplicate.
    client, _ = api
    call(client, "POST", FULL_PROFILE)
    real_find = user_service._find_profile
    calls = iter([None])
    monkeypatch.setattr(user_service, "_find_profile",
                        lambda db, uid, **kw: next(calls, None) or real_find(db, uid, **kw))

    with pytest.raises(user_service.ProfileAlreadyExistsError):
        user_service.create_profile(db_session, 7, UserProfileCreate(full_name="Race"))
    assert stored_profile(db_session, 7).full_name == "Asha Rao"


@pytest.mark.parametrize("field", ["auth_user_id", "id", "is_active", "email", "password", "created_at"])
def test_identity_and_credential_fields_are_rejected_in_the_body(api, db_session, field):
    client, _ = api

    response = call(client, "POST", {**FULL_PROFILE, field: 999})

    assert response.status_code == 422
    assert response.json()["errors"] == [{"field": field, "message": "Extra inputs are not permitted"}]
    assert stored_profile(db_session, 999) is None


def test_auth_user_id_in_the_query_is_ignored(api, db_session):
    client, _ = api

    response = client.post(f"{URL}?auth_user_id=999", json=FULL_PROFILE)

    assert response.json()["auth_user_id"] == 7
    assert stored_profile(db_session, 999) is None


# --- Validation ------------------------------------------------------------------------------

INVALID_VALUES = [
    ("full_name", None),
    ("full_name", ""),
    ("full_name", "   "),
    ("full_name", "A" * 256),
    ("full_name", "Asha\nRao"),
    ("phone_number", "12345"),
    ("phone_number", "call me"),
    ("phone_number", "+0123456789"),
    ("phone_number", "1" * 31),
    ("date_of_birth", (date.today() + timedelta(days=1)).isoformat()),
    ("date_of_birth", "1899-12-31"),
    ("date_of_birth", "2001-02-30"),
    ("date_of_birth", "12/04/1995"),
    ("gender", "female"),
    ("gender", "UNKNOWN"),
    ("gender", ""),
    ("profile_image", "javascript:alert(1)"),
    ("profile_image", "data:image/png;base64,AAAA"),
    ("profile_image", "ftp://example.com/a.png"),
    ("profile_image", "avatar.png"),
    ("profile_image", "/media/../../etc/passwd.png"),
    ("profile_image", "/media/avatar.exe"),
    ("profile_image", "//evil.example.com/a.png"),
    ("profile_image", "https://user:pass@example.com/a.png"),
    ("profile_image", "https:///a.png"),
    ("profile_image", "https://example.com/a b.png"),
    ("profile_image", "https://example.com/" + "a" * 500),
]


@pytest.mark.parametrize(("field", "value"), INVALID_VALUES, ids=lambda v: str(v)[:40])
def test_invalid_values_are_rejected_on_create(api, db_session, field, value):
    client, _ = api

    response = call(client, "POST", {**FULL_PROFILE, field: value})

    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "Validation failed"
    assert [error["field"] for error in body["errors"]] == [field]
    assert stored_profile(db_session, 7) is None


def test_validation_errors_do_not_echo_submitted_values(api):
    client, _ = api

    response = call(client, "POST", {"full_name": "Asha", "phone_number": "secret-555"})

    assert "secret-555" not in response.text


def test_missing_full_name_is_reported(api):
    client, _ = api

    response = call(client, "POST", {"phone_number": "+919876543210"})

    assert response.status_code == 422
    assert response.json()["errors"] == [{"field": "full_name", "message": "Field required"}]


def test_malformed_json_is_reported(api):
    client, _ = api

    response = client.post(URL, content=b"{not json", headers={"Content-Type": "application/json"})

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "body"


@pytest.mark.parametrize("image", ["/media/avatars/7.png", "/static/u_7-a.JPEG", "http://localhost:8080/a.webp",
                                   "https://cdn.example.com/a?size=64"])
def test_valid_profile_images_are_accepted(api, image):
    client, _ = api
    assert call(client, "POST", {"full_name": "A", "profile_image": image}).status_code == 201


@pytest.mark.parametrize("gender", ["MALE", "FEMALE", "OTHER", "PREFER_NOT_TO_SAY"])
def test_documented_genders_are_accepted(api, gender):
    client, _ = api
    assert call(client, "POST", {"full_name": "A", "gender": gender}).json()["gender"] == gender


def test_boundary_values_are_accepted(api):
    client, _ = api

    response = call(client, "POST", {"full_name": "A" * 255, "date_of_birth": date.today().isoformat(),
                                     "phone_number": "1234567"})

    assert response.status_code == 201


# --- GET ---------------------------------------------------------------------------------------

def test_get_profile(api):
    client, _ = api
    created = call(client, "POST", FULL_PROFILE).json()

    response = call(client, "GET")

    assert response.status_code == 200
    assert response.json() == created


def test_get_profile_when_none_exists(api):
    client, _ = api

    response = call(client, "GET")

    assert response.status_code == 404
    assert response.json() == {"detail": "User profile not found"}


def test_users_only_see_their_own_profile(api):
    client, auth_as = api
    call(client, "POST", FULL_PROFILE)

    auth_as(8)
    assert call(client, "GET").status_code == 404
    call(client, "POST", {"full_name": "Ravi"})
    assert call(client, "GET").json()["full_name"] == "Ravi"

    auth_as(7)
    assert call(client, "GET").json()["full_name"] == "Asha Rao"


# --- PUT: full update --------------------------------------------------------------------------

def test_put_replaces_every_field(api):
    client, _ = api
    created = call(client, "POST", FULL_PROFILE).json()

    response = call(client, "PUT", {"full_name": "Asha R.", "gender": "OTHER"})

    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Asha R."
    assert body["gender"] == "OTHER"
    # Omitted optional fields are cleared by a full update.
    assert (body["phone_number"], body["date_of_birth"], body["profile_image"]) == (None, None, None)
    assert (body["id"], body["auth_user_id"], body["created_at"]) == (created["id"], 7, created["created_at"])


def test_put_requires_full_name(api):
    client, _ = api
    call(client, "POST", FULL_PROFILE)

    response = call(client, "PUT", {"gender": "OTHER"})

    assert response.status_code == 422
    assert call(client, "GET").json()["gender"] == "FEMALE"


def test_put_validates_like_create(api):
    client, _ = api
    call(client, "POST", FULL_PROFILE)
    assert call(client, "PUT", {"full_name": "A", "phone_number": "12"}).status_code == 422


def test_put_rejects_auth_user_id(api):
    client, _ = api
    call(client, "POST", FULL_PROFILE)
    assert call(client, "PUT", {**FULL_PROFILE, "auth_user_id": 8}).status_code == 422


def test_put_without_a_profile(api):
    client, _ = api
    assert call(client, "PUT", FULL_PROFILE).status_code == 404


# --- PATCH: partial update ---------------------------------------------------------------------

def test_patch_changes_only_the_fields_sent(api):
    client, _ = api
    call(client, "POST", FULL_PROFILE)

    response = call(client, "PATCH", {"phone_number": "(020) 7946-0958"})

    assert response.status_code == 200
    body = response.json()
    assert body["phone_number"] == "02079460958"
    assert (body["full_name"], body["gender"], body["date_of_birth"]) == ("Asha Rao", "FEMALE", "1995-04-12")


def test_patch_null_clears_an_optional_field(api):
    client, _ = api
    call(client, "POST", FULL_PROFILE)

    body = call(client, "PATCH", {"profile_image": None, "gender": None}).json()

    assert (body["profile_image"], body["gender"]) == (None, None)
    assert body["phone_number"] == "+919876543210"


def test_patch_cannot_clear_full_name(api):
    client, _ = api
    call(client, "POST", FULL_PROFILE)

    response = call(client, "PATCH", {"full_name": None})

    assert response.status_code == 422
    assert response.json()["errors"] == [{"field": "full_name", "message": "full_name cannot be null"}]


def test_patch_with_an_empty_body_is_rejected(api):
    client, _ = api
    call(client, "POST", FULL_PROFILE)

    response = call(client, "PATCH", {})

    assert response.status_code == 422
    assert response.json()["errors"] == [{"field": "body", "message": "Send at least one field to update"}]


@pytest.mark.parametrize(("field", "value"), [("gender", "ROBOT"), ("date_of_birth", "3000-01-01"),
                                               ("profile_image", "avatar.png"), ("auth_user_id", 8)])
def test_patch_validates_fields(api, field, value):
    client, _ = api
    call(client, "POST", FULL_PROFILE)
    assert call(client, "PATCH", {field: value}).status_code == 422


def test_patch_without_a_profile(api):
    client, _ = api
    assert call(client, "PATCH", {"full_name": "A"}).status_code == 404


def test_patch_only_affects_the_callers_profile(api):
    client, auth_as = api
    call(client, "POST", FULL_PROFILE)
    auth_as(8)
    call(client, "POST", {"full_name": "Ravi"})

    call(client, "PATCH", {"full_name": "Ravi Kumar"})

    auth_as(7)
    assert call(client, "GET").json()["full_name"] == "Asha Rao"


# --- DELETE: deactivate ------------------------------------------------------------------------

def test_delete_deactivates_and_preserves_the_record(api, db_session):
    client, _ = api
    created = call(client, "POST", FULL_PROFILE).json()

    response = call(client, "DELETE")

    assert response.status_code == 200
    assert response.json() == {"message": "User profile deactivated"}
    profile = stored_profile(db_session, 7)
    assert profile is not None and profile.id == created["id"]
    assert profile.is_active is False
    assert profile.full_name == "Asha Rao" and profile.phone_number == "+919876543210"


@pytest.mark.parametrize(("method", "body"), ENDPOINTS)
def test_every_operation_is_rejected_after_deactivation(api, db_session, method, body):
    client, _ = api
    call(client, "POST", FULL_PROFILE)
    call(client, "DELETE")

    response = call(client, method, body)

    assert response.status_code == 403
    assert response.json() == {"detail": "User profile is deactivated"}
    assert stored_profile(db_session, 7).full_name == "Asha Rao"


def test_delete_without_a_profile(api):
    client, _ = api
    assert call(client, "DELETE").status_code == 404


def test_deactivation_does_not_affect_other_users(api):
    client, auth_as = api
    call(client, "POST", FULL_PROFILE)
    auth_as(8)
    call(client, "POST", {"full_name": "Ravi"})
    call(client, "DELETE")

    auth_as(7)
    assert call(client, "GET").status_code == 200


def test_deactivation_does_not_call_the_auth_service(api):
    client, _ = api
    calls = []
    app.dependency_overrides[get_auth_client] = lambda: httpx.Client(
        transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(500)))
    call(client, "POST", FULL_PROFILE)

    call(client, "DELETE")

    # The caller is set directly in these tests, so any request here would be the profile code
    # trying to change the Authentication Service account.
    assert calls == []
