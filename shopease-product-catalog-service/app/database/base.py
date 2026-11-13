"""The declarative base shared by every ORM model, and the timestamp columns they reuse.

Models import Base from here. The engine and sessions live in app/database/connection.py, so
models can be imported (for example by Alembic or tests) without opening a database connection.
"""

from datetime import datetime, timezone

from sqlalchemy import MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.database.types import UTCDateTime

# Predictable constraint names, so that Alembic can later alter or drop them by name.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utc_now() -> datetime:
    """The current time as a timezone-aware UTC datetime, to the whole second.

    The timestamp columns are MySQL DATETIME, which stores whole seconds and rounds any fraction.
    Without truncation, a response right after a write would show 12:00:14.925 while the row
    holds 12:00:15, and a later read would return a different time.
    """
    return datetime.now(timezone.utc).replace(microsecond=0)


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class CreatedAtMixin:
    """created_at, set once when the row is inserted. Timestamp columns come last in each table.

    The application fills it (default=utc_now), so the value is UTC whatever the database's
    time zone. server_default covers rows inserted outside the ORM; app/database/connection.py
    sets each MySQL session's time zone to UTC, so NOW() is UTC there too.
    """

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, server_default=func.now(), sort_order=100
    )


class TimestampMixin(CreatedAtMixin):
    """created_at plus updated_at, which is refreshed on every ORM update."""

    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now, server_default=func.now(),
        sort_order=101,  # after created_at, at the end of the table
    )
