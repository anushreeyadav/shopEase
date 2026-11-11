"""Business logic for user profiles. No HTTP code here: routers translate these errors.

Every function takes the caller's auth_user_id, which comes only from the Authentication
Service's verify-token response, and every query filters on it. There is no way to
address a profile by its own ID, so one user can never reach another user's profile.

Each function that writes commits its own transaction. On a database error the session
is rolled back (see get_db), so a request never leaves partial changes.

A deactivated profile (is_active = False) keeps its row, but every operation here rejects
it with ProfileDeactivatedError. Reactivation is reserved for a future admin flow.
Deactivating a profile never changes the user's account in the Authentication Service.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.user_model import UserProfile
from app.schemas.user_schema import UserProfileCreate, UserProfileReplace

_EDITABLE_FIELDS = tuple(UserProfileReplace.model_fields)


class ProfileNotFoundError(Exception):
    """The caller has no profile yet."""


class ProfileAlreadyExistsError(Exception):
    """The caller already has a profile; each auth user has at most one."""


class ProfileDeactivatedError(Exception):
    """The caller's profile exists but is deactivated."""


def _find_profile(db: Session, auth_user_id: int, *, for_update: bool = False) -> UserProfile | None:
    statement = select(UserProfile).where(UserProfile.auth_user_id == auth_user_id)
    if for_update:
        # Locks the row until commit, so concurrent updates of one profile are applied in turn.
        statement = statement.with_for_update()
    return db.scalars(statement).one_or_none()


def get_active_profile(db: Session, auth_user_id: int, *, for_update: bool = False) -> UserProfile:
    profile = _find_profile(db, auth_user_id, for_update=for_update)
    if profile is None:
        raise ProfileNotFoundError
    if not profile.is_active:
        raise ProfileDeactivatedError
    return profile


def _reject_existing(profile: UserProfile | None) -> None:
    if profile is not None:
        raise ProfileDeactivatedError if not profile.is_active else ProfileAlreadyExistsError


def create_profile(db: Session, auth_user_id: int, data: UserProfileCreate) -> UserProfile:
    _reject_existing(_find_profile(db, auth_user_id))

    profile = UserProfile(auth_user_id=auth_user_id, **data.model_dump())
    db.add(profile)
    try:
        db.commit()
    except IntegrityError:
        # Another request created the profile between the check and the insert. The unique
        # constraint on auth_user_id stopped the duplicate; report it like the check would.
        db.rollback()
        existing = _find_profile(db, auth_user_id)
        if existing is None:
            raise
        _reject_existing(existing)
    return profile


def get_profile(db: Session, auth_user_id: int) -> UserProfile:
    return get_active_profile(db, auth_user_id)


def replace_profile(db: Session, auth_user_id: int, data: UserProfileReplace) -> UserProfile:
    profile = get_active_profile(db, auth_user_id, for_update=True)
    # Every editable field is written, so an omitted optional field becomes null.
    for field in _EDITABLE_FIELDS:
        setattr(profile, field, getattr(data, field))
    db.commit()
    return profile


def update_profile(db: Session, auth_user_id: int, changes: dict[str, Any]) -> UserProfile:
    profile = get_active_profile(db, auth_user_id, for_update=True)
    for field, value in changes.items():
        if field not in _EDITABLE_FIELDS:  # schemas already forbid this; defence in depth
            raise ValueError(f"{field} cannot be updated")
        setattr(profile, field, value)
    db.commit()
    return profile


def deactivate_profile(db: Session, auth_user_id: int) -> UserProfile:
    profile = get_active_profile(db, auth_user_id, for_update=True)
    profile.is_active = False
    db.commit()
    return profile
