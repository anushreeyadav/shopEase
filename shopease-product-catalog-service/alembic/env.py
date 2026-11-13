"""Alembic migration environment.

The database URL is not in alembic.ini. It is built by app.core.config from the MYSQL_*
environment variables (or .env), the same settings the application uses, so migrations
always target the Catalog Service database and never contain credentials.

Tests may pass their own connection in config.attributes["connection"] (see
tests/test_migrations.py); the database-name safety check applies only to the real engine.
"""

from logging.config import fileConfig

from alembic import context

import app.models  # noqa: F401  (registers every table on Base.metadata for autogenerate)
from app.core.config import get_settings
from app.database.base import Base

if context.config.config_file_name is not None and context.config.attributes.get("configure_logger", True):
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# Autogenerate also compares column types and server defaults, not only tables and columns.
COMPARE_OPTIONS = {"compare_type": True, "compare_server_default": True}

# The service database, and the throwaway database used to test downgrades
# (scripts/migration_check.py). Migrations refuse to touch any other database.
ALLOWED_DATABASES = frozenset({"shopease_product_catalog_db", "shopease_product_catalog_test_db"})


def run_migrations_offline() -> None:
    """Write the migration SQL to stdout without connecting to a database."""
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **COMPARE_OPTIONS,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, **COMPARE_OPTIONS)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply the migrations to the configured database (or to a connection a test passed in)."""
    supplied = context.config.attributes.get("connection")
    if supplied is not None:
        _run(supplied)
        return

    from app.database.connection import engine  # only now: creating it needs the MySQL settings

    with engine.connect() as connection:
        # Refuse to run against any other database, such as a mistyped MYSQL_DATABASE.
        current = connection.exec_driver_sql("SELECT DATABASE()").scalar()
        if current not in ALLOWED_DATABASES:
            raise RuntimeError(
                f"Refusing to migrate database {current!r}: expected one of {sorted(ALLOWED_DATABASES)}"
            )
        # End the transaction that the check began. Otherwise Alembic treats it as an outer
        # transaction and never commits the alembic_version update.
        connection.commit()
        _run(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
