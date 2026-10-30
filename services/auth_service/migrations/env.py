"""Alembic environment for auth_service. Migrates auth_db only, as the migration user."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import Connection

from app.config import get_settings
from app.models import Base
from app.models.base import UTCDateTime

config = context.config
if config.config_file_name and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def render_item(type_: str, obj: object, autogen_context) -> str | bool:
    # Freeze the custom type as plain SQLAlchemy types, so migrations don't import app code.
    if type_ == "type" and isinstance(obj, UTCDateTime):
        autogen_context.imports.add("from sqlalchemy.dialects import mysql")
        return 'sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")'
    return False


def configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        render_item=render_item,
        compare_type=True,
        **kwargs,
    )


def run_migrations(connection: Connection) -> None:
    configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Tests pass an open connection; otherwise connect with the migration credentials.
    connection = config.attributes.get("connection")
    if connection is not None:
        run_migrations(connection)
        return
    engine = create_engine(get_settings().migration_database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        run_migrations(connection)
    engine.dispose()


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: print the SQL for review without connecting."""
    configure(url="mysql+pymysql://", literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
