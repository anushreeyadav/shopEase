"""user_db model and schema behaviour, checked on SQLite (constraints are portable)."""

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Base, UserAddress, UserProfile
from app.schemas import AddressRead, AddressWrite, ProfileRead

ADDRESS = {"line1": "12 MG Road", "city": "Bengaluru", "postal_code": "560001", "country": "IN"}


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_profile_uses_the_external_user_id_as_key(session):
    user_id = uuid.uuid4()  # comes from the JWT `sub`, issued by auth_service
    session.add(UserProfile(user_id=user_id, full_name="Asha Rao"))
    session.commit()
    profile = ProfileRead.model_validate(session.get(UserProfile, user_id))
    assert profile.user_id == user_id and profile.phone is None


def test_address_requires_an_existing_profile(session):
    session.add(UserAddress(user_id=uuid.uuid4(), **ADDRESS))
    with pytest.raises(IntegrityError):
        session.commit()


def test_addresses_are_removed_with_their_profile(session):
    profile = UserProfile(user_id=uuid.uuid4())
    session.add(profile)
    session.flush()
    session.add(UserAddress(user_id=profile.user_id, is_default=True, **ADDRESS))
    session.commit()
    address = AddressRead.model_validate(session.scalars(select(UserAddress)).one())
    assert address.is_default and address.country == "IN"
    session.delete(profile)
    session.commit()
    assert session.scalars(select(UserAddress)).all() == []


def test_address_schema_validation():
    AddressWrite(**ADDRESS)
    with pytest.raises(ValidationError):
        AddressWrite(**{**ADDRESS, "country": "India"})
    with pytest.raises(ValidationError):
        AddressWrite(**ADDRESS, unexpected="field")
