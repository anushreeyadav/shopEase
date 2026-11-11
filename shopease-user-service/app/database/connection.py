"""Database engine, session factory, and the declarative base for ORM models.

Creating the engine does not open a connection; the first query does.
Tables are created only by Alembic migrations, never by Base.metadata.create_all().
"""

import logging
from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)

engine = create_engine(
    get_settings().database_url,
    pool_pre_ping=True,  # replace connections that MySQL has closed while idle
    pool_recycle=3600,  # and never keep one longer than an hour
    hide_parameters=True,  # keep query values, such as phone numbers, out of errors and logs
    # Fail quickly when MySQL is down. func.now() timestamps are always stored in UTC.
    connect_args={"connect_timeout": 5, "init_command": "SET time_zone = '+00:00'"},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    # Predictable constraint names, so that Alembic can later alter or drop them by name.
    metadata = MetaData(naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request.

    Services commit their own work. If the request fails, anything not yet committed is
    rolled back, and the session is always closed, which returns its connection to the pool.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_database_connection(db: Session) -> bool:
    """Return True if the database answers a simple query."""
    try:
        db.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError as exc:
        # Class name only: driver messages can include connection details.
        logger.error("Database connectivity check failed: %s", type(exc).__name__)
        return False
