"""Database engine and reusable session management.

Creating the engine does not open a connection; the first query does.
Tables are created only by Alembic migrations, never by Base.metadata.create_all().

Two ways to get a session:
  - get_db():         FastAPI dependency, one session per request.
  - session_scope():  context manager for scripts and background jobs; commits on success,
                      rolls back on any error, and always closes.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import ExceptionContext
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# MySQL error 3819: "Check constraint '...' is violated." PyMySQL reports it as OperationalError,
# the class it uses for server and connection problems, although it is a data integrity error.
MYSQL_CHECK_CONSTRAINT_VIOLATED = 3819

engine = create_engine(
    get_settings().database_url,
    pool_pre_ping=True,  # replace connections that MySQL has closed while idle
    pool_recycle=3600,  # and never keep one longer than an hour
    hide_parameters=True,  # keep query values out of errors and logs
    connect_args={
        "connect_timeout": 5,  # fail quickly when MySQL is down
        # Every session works in UTC, so NOW() and CURRENT_TIMESTAMP defaults are UTC.
        "init_command": "SET time_zone = '+00:00'",
        # utf8mb4: full Unicode, including emoji, in product names and descriptions.
        "charset": "utf8mb4",
    },
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def translate_check_violation(context: ExceptionContext) -> None:
    """Re-raise a MySQL CHECK constraint violation as IntegrityError.

    Without this, a CHECK violation (for example negative stock) would look like a database
    outage: callers that handle IntegrityError would miss it, and the API would answer 503.
    Query parameters stay hidden, as everywhere else on this engine.
    """
    original = context.original_exception
    code = original.args[0] if getattr(original, "args", None) else None
    if code == MYSQL_CHECK_CONSTRAINT_VIOLATED:
        raise IntegrityError(context.statement, context.parameters, original, hide_parameters=True) from original


event.listen(engine, "handle_error", translate_check_violation)

MYSQL_DUPLICATE_ENTRY = 1062


def is_unique_violation(exc: IntegrityError) -> bool:
    """True if the database refused a write because of a unique constraint.

    Other integrity errors (foreign key, CHECK, NOT NULL) need a different message.
    MySQL reports error 1062; SQLite, used by the tests, says "UNIQUE constraint failed".
    """
    original = exc.orig
    code = original.args[0] if getattr(original, "args", None) else None
    return code == MYSQL_DUPLICATE_ENTRY or "UNIQUE constraint failed" in str(original)


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


@contextmanager
def session_scope() -> Iterator[Session]:
    """A session for code outside a request:

        with session_scope() as db:
            db.add(...)

    Commits when the block ends normally, rolls back if it raises, and always closes.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
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
