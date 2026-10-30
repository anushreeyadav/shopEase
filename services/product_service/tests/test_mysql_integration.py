"""Integration tests for product_service against a real MySQL.

Skipped unless SHOPEASE_MYSQL_TESTS=1. Uses the same environment variables as the service
(MYSQL_HOST, MYSQL_PORT, PRODUCT_DB_*). Point them at a disposable server: see
docs/database_setup.md. The downgrade test drops this service's tables and also needs
SHOPEASE_ALLOW_DESTRUCTIVE_DB_TESTS=1.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from app.config import Settings
from app.db import Database
from app.models import Base

pytestmark = pytest.mark.skipif(
    os.getenv("SHOPEASE_MYSQL_TESTS") != "1", reason="set SHOPEASE_MYSQL_TESTS=1 to run"
)

SERVICE_DIR = Path(__file__).resolve().parents[1]
OWNED_TABLES = {'stock_reservations', 'products', 'inventory', 'categories', 'inventory_movements'}
OTHER_DATABASES = ['auth_db', 'user_db', 'order_db', 'payment_db']
ACCESS_DENIED = {1044, 1142, 1045}


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings()


@pytest.fixture(scope="module")
def migration_engine(settings):
    engine = create_engine(settings.migration_database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def runtime_db(settings):
    database = Database.from_settings(settings)
    yield database
    database.dispose()


def run_alembic(engine, *args) -> None:
    with engine.begin() as connection:
        config = Config(
            str(SERVICE_DIR / "alembic.ini"),
            attributes={"connection": connection, "configure_logger": False},
        )
        getattr(command, args[0])(config, *args[1:])


def assert_denied(exc_info) -> None:
    assert exc_info.value.orig.args[0] in ACCESS_DENIED, exc_info.value.orig


def test_upgrade_is_repeatable_and_matches_models(migration_engine):
    run_alembic(migration_engine, "upgrade", "head")
    run_alembic(migration_engine, "upgrade", "head")
    head = ScriptDirectory.from_config(Config(str(SERVICE_DIR / "alembic.ini"))).get_current_head()
    with migration_engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == head
        assert set(inspect(connection).get_table_names()) == OWNED_TABLES | {"alembic_version"}
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []


def test_runtime_user_can_read_and_write_its_tables(runtime_db, settings):
    runtime_db.ping()
    with runtime_db.session() as session:
        for table in OWNED_TABLES:
            session.execute(text(f"SELECT COUNT(*) FROM `{table}`"))
        session.rollback()
        user = session.execute(text("SELECT CURRENT_USER()")).scalar_one()
    assert user.startswith(settings.db_user + "@")


def test_runtime_user_cannot_change_the_schema(runtime_db):
    with runtime_db.engine.connect() as connection:
        with pytest.raises(DBAPIError) as exc_info:
            connection.execute(text("CREATE TABLE ownership_probe (id INT)"))
    assert_denied(exc_info)


@pytest.mark.parametrize("other_db", OTHER_DATABASES)
@pytest.mark.parametrize("which", ["runtime", "migration"])
def test_no_access_to_other_services_databases(settings, other_db, which):
    url = settings.database_url if which == "runtime" else settings.migration_database_url
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            with pytest.raises(DBAPIError) as exc_info:
                connection.execute(text(f"SHOW TABLES FROM `{other_db}`"))
        assert_denied(exc_info)
    finally:
        engine.dispose()


@pytest.mark.skipif(
    os.getenv("SHOPEASE_ALLOW_DESTRUCTIVE_DB_TESTS") != "1",
    reason="drops this service's tables; set SHOPEASE_ALLOW_DESTRUCTIVE_DB_TESTS=1 on a disposable DB",
)
def test_downgrade_and_upgrade_again(migration_engine):
    run_alembic(migration_engine, "downgrade", "base")
    with migration_engine.connect() as connection:
        assert set(inspect(connection).get_table_names()) == {"alembic_version"}
    run_alembic(migration_engine, "upgrade", "head")
    with migration_engine.connect() as connection:
        assert set(inspect(connection).get_table_names()) == OWNED_TABLES | {"alembic_version"}
