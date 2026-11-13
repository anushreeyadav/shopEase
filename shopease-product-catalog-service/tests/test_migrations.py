"""The Alembic migration creates exactly the schema the models describe, and can be undone.

Runs the real migration scripts against a private SQLite database. For MySQL 8, the same
check is "alembic check" against shopease_product_catalog_db after "alembic upgrade head".
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect

import app.models  # noqa: F401
from app.database.base import Base

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TABLES = {"categories", "products", "inventory_transactions"}


@pytest.fixture
def migration_db():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys = ON")

    with engine.begin() as conn:
        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
        config.attributes["connection"] = conn
        config.attributes["configure_logger"] = False
        yield config, conn
    engine.dispose()


def test_single_head_and_linear_history():
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert len(script.get_heads()) == 1
    assert [rev.revision for rev in script.walk_revisions()] == ["c4a7d2e91b30", "5b8e2f0c9d14"]


def test_upgrade_creates_the_model_schema(migration_db):
    config, conn = migration_db
    command.upgrade(config, "head")

    assert TABLES <= set(inspect(conn).get_table_names())
    context = MigrationContext.configure(conn, opts={"compare_type": True})
    differences = compare_metadata(context, Base.metadata)
    assert differences == [], differences


def test_upgrade_creates_check_constraints(migration_db):
    config, conn = migration_db
    command.upgrade(config, "head")
    names = {table: {ck["name"] for ck in inspect(conn).get_check_constraints(table)} for table in TABLES}
    assert {"ck_products_stock_quantity_non_negative", "ck_products_discount_price_valid",
            "ck_products_price_non_negative"} <= names["products"]
    assert {"ck_inventory_transactions_stock_arithmetic", "ck_inventory_transactions_quantity_positive",
            "ck_inventory_transactions_transaction_type"} <= names["inventory_transactions"]
    assert "ck_categories_name_not_blank" in names["categories"]


def test_downgrade_removes_everything(migration_db):
    config, conn = migration_db
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    assert not TABLES & set(inspect(conn).get_table_names())
