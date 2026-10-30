"""Database-layer tests for product_service that need no MySQL (SQLite stands in for schema checks)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.config import Settings
from app.db import Database
from app.dependencies import get_db_session
from app.models import Base

SERVICE_DIR = Path(__file__).resolve().parents[1]
OWNED_TABLES = {'stock_reservations', 'products', 'inventory', 'categories', 'inventory_movements'}
# Identifiers owned by other services: plain indexed columns, never foreign keys.
EXTERNAL_ID_COLUMNS = ['stock_reservations.order_id', 'inventory_movements.reference_id']


def alembic_config(connection) -> Config:
    return Config(
        str(SERVICE_DIR / "alembic.ini"),
        attributes={"connection": connection, "configure_logger": False},
    )


def test_metadata_holds_exactly_the_owned_tables():
    assert set(Base.metadata.tables) == OWNED_TABLES


def test_foreign_keys_never_leave_this_database():
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            assert fk.column.table.name in OWNED_TABLES, f"{table.name} -> {fk.target_fullname}"


@pytest.mark.parametrize("qualified", EXTERNAL_ID_COLUMNS)
def test_external_ids_are_indexed_without_foreign_keys(qualified):
    table_name, column_name = qualified.split(".")
    table = Base.metadata.tables[table_name]
    column = table.c[column_name]
    assert not column.foreign_keys
    leading_columns = [list(table.primary_key.columns)[0].name]
    leading_columns += [list(ix.columns)[0].name for ix in table.indexes]
    leading_columns += [
        list(c.columns)[0].name for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"
    ]
    assert column_name in leading_columns, f"{qualified} needs an index"


def test_single_linear_migration_history():
    script = ScriptDirectory.from_config(alembic_config(None))
    assert len(script.get_heads()) == 1
    for revision in script.walk_revisions():
        assert revision.down_revision is None or isinstance(revision.down_revision, str)


def test_migrations_match_models_and_are_repeatable(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migrate.db'}")
    with engine.connect() as connection:
        config = alembic_config(connection)
        command.upgrade(config, "head")
        command.upgrade(config, "head")  # a second run is a no-op
        assert set(inspect(connection).get_table_names()) == OWNED_TABLES | {"alembic_version"}
        # Types are compared on MySQL (integration test); SQLite has too few distinct types.
        context = MigrationContext.configure(connection, opts={"compare_type": False})
        assert compare_metadata(context, Base.metadata) == []

        command.downgrade(config, "base")
        assert set(inspect(connection).get_table_names()) == {"alembic_version"}
        command.upgrade(config, "head")
        assert set(inspect(connection).get_table_names()) == OWNED_TABLES | {"alembic_version"}
    engine.dispose()


def _request_with_session(session) -> MagicMock:
    request = MagicMock()
    request.app.state.db.session.return_value = session
    return request


def test_request_session_is_closed_without_rollback_on_success():
    session = MagicMock()
    dependency = get_db_session(_request_with_session(session))
    assert next(dependency) is session
    with pytest.raises(StopIteration):
        next(dependency)
    session.rollback.assert_not_called()
    session.close.assert_called_once()


def test_request_session_rolls_back_and_closes_on_error():
    session = MagicMock()
    dependency = get_db_session(_request_with_session(session))
    next(dependency)
    with pytest.raises(RuntimeError):
        dependency.throw(RuntimeError("route failed"))
    session.rollback.assert_called_once()
    session.close.assert_called_once()


def test_session_scope_commits_or_rolls_back():
    database = Database("sqlite://")
    database.session_factory = MagicMock()
    ok, failing = MagicMock(), MagicMock()
    database.session_factory.side_effect = [ok, failing]

    with database.session_scope():
        pass
    ok.commit.assert_called_once()
    ok.close.assert_called_once()

    with pytest.raises(ValueError):
        with database.session_scope():
            raise ValueError("job failed")
    failing.commit.assert_not_called()
    failing.rollback.assert_called_once()
    failing.close.assert_called_once()


@pytest.fixture
def clean_db_env(monkeypatch):
    for suffix in ("NAME", "USER", "PASSWORD", "MIGRATION_USER", "MIGRATION_PASSWORD"):
        monkeypatch.delenv(f"PRODUCT_DB_{suffix}", raising=False)


def test_database_urls_never_reveal_passwords(clean_db_env):
    settings = Settings(
        _env_file=None, PRODUCT_DB_PASSWORD="runtime-secret", PRODUCT_DB_MIGRATION_PASSWORD="ddl-secret"
    )
    assert settings.database_url.database == "product_db"
    assert settings.database_url.username == "product_svc"
    assert settings.migration_database_url.username == "product_migrator"
    for url in (settings.database_url, settings.migration_database_url):
        assert "secret" not in str(url) and "secret" not in repr(url)


def test_migration_url_requires_migration_credentials(clean_db_env):
    with pytest.raises(RuntimeError, match="PRODUCT_DB_MIGRATION"):
        Settings(_env_file=None).migration_database_url
