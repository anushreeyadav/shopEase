"""Alembic migration environment.

The database URL is not in alembic.ini. It is built by app.core.config from the MYSQL_*
environment variables (or .env), the same settings the application uses, so migrations
always target the User Service database and never contain credentials.
"""

from logging.config import fileConfig

from alembic import context

from app.core.config import get_settings
from app.database.connection import Base, engine
# Imported so that their tables are registered on Base.metadata for autogenerate.
from app.models.address_model import UserAddress  # noqa: F401
from app.models.user_model import UserProfile  # noqa: F401

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

target_metadata = Base.metadata

# Autogenerate also compares column types and server defaults, not only tables and columns.
COMPARE_OPTIONS = {"compare_type": True, "compare_server_default": True}

EXPECTED_DATABASE = "shopease_user_db"


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


def run_migrations_online() -> None:
    """Apply the migrations to the configured database."""
    with engine.connect() as connection:
        # Every table operation is unqualified, so it acts only on the connected database.
        # Refuse to run against any other one, such as a mistyped MYSQL_DATABASE.
        current = connection.exec_driver_sql("SELECT DATABASE()").scalar()
        if current != EXPECTED_DATABASE:
            raise RuntimeError(
                f"Refusing to migrate database {current!r}: expected {EXPECTED_DATABASE!r}"
            )
        # End the transaction that the check began. Otherwise Alembic treats it as an outer
        # transaction and never commits the alembic_version update.
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, **COMPARE_OPTIONS)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
