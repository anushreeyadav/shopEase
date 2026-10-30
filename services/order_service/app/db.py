"""Engine and sessions for order_service. Only this service connects to order_db."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings


class Database:
    def __init__(self, url: URL | str, **engine_options: Any) -> None:
        # create_engine does not connect yet; the first connection happens on first use.
        self.engine = create_engine(url, **engine_options)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> "Database":
        return cls(
            settings.database_url,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_size=settings.db_pool_size,
            connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
        )

    def ping(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def session(self) -> Session:
        return self.session_factory()

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        """Unit of work outside a request (jobs, scripts): commit on success, roll back on error."""
        session = self.session()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()
