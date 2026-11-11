"""Checks for the database layer that need no MySQL: models, constraints metadata, phone numbers, get_db."""

import pytest
from pydantic import ValidationError

from app.core.phone_utils import normalize_phone_number
from app.database import connection
from app.models import UserAddress, UserProfile
from app.schemas.address_schema import AddressCreate
from app.schemas.user_schema import UserProfileCreate


@pytest.mark.parametrize(("raw", "normalized"), [
    ("+91 98765-43210", "+919876543210"),
    ("(020) 7946-0958", "02079460958"),
    ("0091 98765 43210", "+919876543210"),
    ("  555.123.4567 ", "5551234567"),
])
def test_phone_numbers_are_normalized(raw, normalized):
    assert normalize_phone_number(raw) == normalized


@pytest.mark.parametrize("raw", ["12345", "+0123456789", "phone-me", "+91 98765 43210 ext 5", "1" * 16])
def test_invalid_phone_numbers_are_rejected_without_echoing_them(raw):
    with pytest.raises(ValueError) as error:
        normalize_phone_number(raw)
    assert raw not in str(error.value)


def test_schemas_normalize_phone_numbers():
    profile = UserProfileCreate(full_name="Asha", phone_number="+91 98765-43210")
    address = AddressCreate(full_name="Asha", phone_number="(020) 7946-0958", address_line_1="1 Road",
                            city="Pune", state="MH", country="India", postal_code="411001")
    assert (profile.phone_number, address.phone_number) == ("+919876543210", "02079460958")
    with pytest.raises(ValidationError):
        UserProfileCreate(full_name="Asha", phone_number="12")


def test_models_normalize_phone_numbers():
    assert UserProfile(auth_user_id=1, full_name="A", phone_number="+44 20 7946 0958").phone_number == "+442079460958"


def test_profile_has_no_credential_columns():
    columns = set(UserProfile.__table__.columns.keys())
    assert not columns & {"email", "password", "password_hash", "hashed_password", "token", "username", "login"}


def test_auth_user_id_has_a_unique_constraint():
    column = UserProfile.__table__.c.auth_user_id
    assert column.unique and not column.nullable


def test_address_user_id_is_indexed():
    assert UserAddress.__table__.c.user_id.index


def test_address_foreign_key_cascades_on_delete():
    (foreign_key,) = UserAddress.__table__.c.user_id.foreign_keys
    assert foreign_key.target_fullname == "user_profiles.id"
    assert foreign_key.ondelete == "CASCADE"


def test_get_db_rolls_back_and_closes_on_error(monkeypatch):
    calls = []

    class FakeSession:
        def rollback(self): calls.append("rollback")
        def close(self): calls.append("close")

    monkeypatch.setattr(connection, "SessionLocal", FakeSession)
    dependency = connection.get_db()
    next(dependency)
    with pytest.raises(RuntimeError):
        dependency.throw(RuntimeError("request failed"))
    assert calls == ["rollback", "close"]


def test_get_db_closes_without_rollback_on_success(monkeypatch):
    calls = []

    class FakeSession:
        def rollback(self): calls.append("rollback")
        def close(self): calls.append("close")

    monkeypatch.setattr(connection, "SessionLocal", FakeSession)
    dependency = connection.get_db()
    next(dependency)
    dependency.close()
    assert calls == ["close"]
