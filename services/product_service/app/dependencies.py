"""FastAPI dependencies for product_service routes."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db_session(request: Request) -> Iterator[Session]:
    """One session per request. Routes commit explicitly; anything not committed is rolled back.

    An exception raised by the route (including HTTPException) propagates into this
    generator, so the transaction is rolled back before the session is closed.
    """
    session = request.app.state.db.session()
    try:
        yield session
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
DbSession = Annotated[Session, Depends(get_db_session)]
