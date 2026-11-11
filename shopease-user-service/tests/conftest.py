"""Test settings and fixtures. Environment values are set before the app is imported.

Database tests run against SQLite in memory by default. With USER_SERVICE_TEST_DB=mysql they
run against the real shopease_user_db from .env, whose tables must already exist
(alembic upgrade head). Either way each test runs inside a transaction that is rolled back,
so no data is left behind.
"""

import os
from collections.abc import Callable, Iterator

import httpx
import pytest

USE_MYSQL = os.environ.get("USER_SERVICE_TEST_DB", "").lower() == "mysql"

os.environ.update({
    "AUTH_SERVICE_VERIFY_URL": "http://auth.test/api/auth/verify-token",
    "AUTH_SERVICE_TIMEOUT_SECONDS": "2",
})
if not USE_MYSQL:
    os.environ.update({"MYSQL_USER": "test_user", "MYSQL_PASSWORD": "test-db-password-not-real"})

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402,F401  (registers the tables)
from app.core.security import AuthenticatedUser, get_current_authenticated_user  # noqa: E402
from app.database import connection  # noqa: E402
from app.database.connection import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402

VERIFIED_USER = {"id": 7, "full_name": "Test User", "email": "test@example.com", "role": "USER", "is_active": True}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def fake_auth_service(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    """An HTTP client whose requests go to handler instead of the real Authentication Service."""
    return httpx.Client(transport=httpx.MockTransport(handler))


def _sqlite_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # one shared in-memory database
    )

    # pysqlite's own transaction handling breaks SAVEPOINTs; let SQLAlchemy issue BEGIN instead.
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _record):
        dbapi_connection.isolation_level = None
        dbapi_connection.execute("PRAGMA foreign_keys = ON")

    @event.listens_for(engine, "begin")
    def _on_begin(conn):
        conn.exec_driver_sql("BEGIN")

    # Tests only: the real database is created by Alembic migrations.
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    if USE_MYSQL:
        yield connection.engine
    else:
        engine = _sqlite_engine()
        yield engine
        engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A session whose commits are released savepoints inside one transaction that is rolled back."""
    conn = db_engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint",
                      autoflush=False, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        conn.close()


class AuthAs:
    """Switches the authenticated caller, as if the Authentication Service had verified their token."""

    def __call__(self, auth_user_id: int, role: str = "USER") -> None:
        user = AuthenticatedUser(auth_user_id=auth_user_id, full_name=f"User {auth_user_id}",
                                 email=f"user{auth_user_id}@example.com", role=role)
        app.dependency_overrides[get_current_authenticated_user] = lambda: user


@pytest.fixture
def api(db_session: Session) -> Iterator[tuple[TestClient, AuthAs]]:
    """The real app with a test database and a switchable authenticated user (default: user 7)."""
    app.dependency_overrides[get_db] = lambda: db_session
    auth_as = AuthAs()
    auth_as(7)
    try:
        yield TestClient(app), auth_as
    finally:
        app.dependency_overrides.clear()
