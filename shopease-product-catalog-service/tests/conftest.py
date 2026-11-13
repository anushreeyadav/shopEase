"""Test settings and fixtures. Environment values are set before the app is imported.

Database tests run against SQLite in memory by default. With CATALOG_SERVICE_TEST_DB=mysql they
run against the real shopease_product_catalog_db from .env, whose tables must already exist
(alembic upgrade head). Either way each test runs inside a transaction that is rolled back.
"""

import os
from collections.abc import Iterator

import pytest

USE_MYSQL = os.environ.get("CATALOG_SERVICE_TEST_DB", "").lower() == "mysql"

os.environ.update({
    "AUTH_SERVICE_VERIFY_URL": "http://auth.test/api/auth/verify-token",
    "AUTH_SERVICE_TIMEOUT_SECONDS": "2",
    "LOW_STOCK_THRESHOLD": "5",
})
if not USE_MYSQL:
    os.environ.update({"MYSQL_USER": "test_user", "MYSQL_PASSWORD": "test-db-password-not-real"})

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402,F401  (registers the tables)
from app.core.security import (  # noqa: E402
    AuthenticatedUser,
    get_current_authenticated_user,
    get_optional_user,
)
from app.database import connection  # noqa: E402
from app.database.base import Base  # noqa: E402
from app.database.connection import get_db  # noqa: E402
from app.main import app  # noqa: E402


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
    """Switches the caller, as if the Authentication Service had verified their token.

    auth_as(None) makes the caller anonymous (no token sent).
    """

    def __call__(self, auth_user_id: int | None, role: str = "USER") -> None:
        app.dependency_overrides.pop(get_current_authenticated_user, None)
        app.dependency_overrides.pop(get_optional_user, None)
        if auth_user_id is None:
            return  # real dependencies: no Authorization header -> anonymous / 401
        user = AuthenticatedUser(auth_user_id=auth_user_id, full_name=f"User {auth_user_id}",
                                 email=f"user{auth_user_id}@example.com", role=role)
        app.dependency_overrides[get_current_authenticated_user] = lambda: user
        app.dependency_overrides[get_optional_user] = lambda: user

    def admin(self) -> None:
        self(1, role="ADMIN")


@pytest.fixture
def api(db_session: Session) -> Iterator[tuple[TestClient, AuthAs]]:
    """The real app with a test database and a switchable caller (default: an admin)."""
    app.dependency_overrides[get_db] = lambda: db_session
    auth_as = AuthAs()
    auth_as.admin()
    try:
        yield TestClient(app), auth_as
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client(api) -> TestClient:
    return api[0]


@pytest.fixture
def auth_as(api) -> AuthAs:
    return api[1]


@pytest.fixture
def category(client: TestClient) -> dict:
    response = client.post("/api/categories", json={"name": "Footwear", "description": "Shoes and boots"})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def make_product(client: TestClient, category: dict):
    counter = iter(range(1, 1000))

    def _make(**overrides) -> dict:
        body = {
            "sku": f"SKU-{next(counter):03d}",
            "name": "Trail Runner",
            "price": "79.99",
            "category_id": category["id"],
            "initial_stock": 10,
            **overrides,
        }
        response = client.post("/api/products", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    return _make
