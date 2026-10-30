"""auth_db model and schema behaviour, checked on SQLite (constraints are portable)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.models import AuthUser, Base, RefreshToken, Role, ServiceClient
from app.schemas import AuthUserRead, RegisterRequest


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def make_user(email="asha.rao@example.com") -> AuthUser:
    return AuthUser(email=email, password_hash="argon2id$placeholder")


def test_defaults_and_read_schema_hide_the_hash(session):
    user = make_user()
    session.add(user)
    session.commit()
    assert isinstance(user.id, uuid.UUID)
    assert user.role is Role.CUSTOMER
    assert user.created_at.tzinfo is UTC
    body = AuthUserRead.model_validate(user).model_dump(mode="json")
    assert set(body) == {"user_id", "email", "role", "created_at"}
    assert body["role"] == "customer"


def test_email_is_unique(session):
    session.add_all([make_user(), make_user()])
    with pytest.raises(IntegrityError):
        session.commit()


def test_failed_login_attempts_cannot_go_negative(session):
    user = make_user()
    user.failed_login_attempts = -1
    session.add(user)
    with pytest.raises(IntegrityError, match="failed_login_attempts"):
        session.commit()


def test_refresh_tokens_are_removed_with_their_user(session):
    user = make_user()
    session.add(user)
    session.flush()
    session.add(
        RefreshToken(user_id=user.id, token_hash="a" * 64, expires_at=datetime.now(UTC) + timedelta(days=7))
    )
    session.commit()
    session.delete(user)
    session.commit()
    assert session.scalars(select(RefreshToken)).all() == []


def test_naive_datetimes_are_rejected(session):
    user = make_user()
    user.locked_until = datetime(2026, 10, 30, 12, 0)  # no tzinfo
    session.add(user)
    with pytest.raises(StatementError, match="Naive datetime"):
        session.commit()


def test_service_client_scopes_round_trip(session):
    session.add(ServiceClient(client_id="svc:order", secret_hash="x", allowed_scopes=["inventory:reserve"]))
    session.commit()
    client = session.get(ServiceClient, "svc:order")
    assert client.allowed_scopes == ["inventory:reserve"] and client.active is True


def test_register_request_validation():
    RegisterRequest(email="asha.rao@example.com", password="a-long-enough-password")
    with pytest.raises(ValidationError):
        RegisterRequest(email="not-an-email", password="a-long-enough-password")
    with pytest.raises(ValidationError):
        RegisterRequest(email="asha.rao@example.com", password="short")
