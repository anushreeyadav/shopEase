"""Profile and address rules for user_service.

Identity is always the verified token's `sub` (never a header or body field). Address
queries are always filtered by owner, so another user's address is indistinguishable from
a missing one (404, rest_api_notes.md §1.10). Logs carry IDs only, never personal data.
"""

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import UserAddress, UserProfile
from shopease_shared import ShopEaseError


def address_not_found() -> ShopEaseError:
    return ShopEaseError(404, "ADDRESS_NOT_FOUND", "No such address.")


def get_or_create_profile(session: Session, user_id: uuid.UUID) -> UserProfile:
    """Lazy creation (ADR-09). Two first requests racing each other both end up reading one row."""
    profile = session.get(UserProfile, user_id)
    if profile is not None:
        return profile
    session.add(UserProfile(user_id=user_id))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
    return session.get(UserProfile, user_id)


def update_profile(session: Session, user_id: uuid.UUID, changes: dict[str, Any]) -> UserProfile:
    profile = get_or_create_profile(session, user_id)
    for field, value in changes.items():
        setattr(profile, field, value)
    session.commit()
    return profile


def list_addresses(session: Session, user_id: uuid.UUID, limit: int, offset: int) -> tuple[list[UserAddress], int]:
    owned = UserAddress.user_id == user_id
    total = session.scalar(select(func.count()).select_from(UserAddress).where(owned))
    items = session.scalars(
        select(UserAddress)
        .where(owned)
        .order_by(UserAddress.is_default.desc(), UserAddress.created_at, UserAddress.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return list(items), total


def get_owned_address(session: Session, user_id: uuid.UUID, address_id: uuid.UUID, lock: bool = False) -> UserAddress:
    query = select(UserAddress).where(UserAddress.id == address_id, UserAddress.user_id == user_id)
    if lock:
        query = query.with_for_update()
    address = session.scalars(query).one_or_none()
    if address is None:
        raise address_not_found()
    return address


def _lock_profile(session: Session, user_id: uuid.UUID) -> None:
    # Serializes default-address changes per user (MySQL has no partial unique index).
    get_or_create_profile(session, user_id)
    session.get(UserProfile, user_id, with_for_update=True, populate_existing=True)


def _clear_other_defaults(session: Session, user_id: uuid.UUID, keep: uuid.UUID | None) -> None:
    session.execute(
        update(UserAddress)
        .where(UserAddress.user_id == user_id, UserAddress.is_default.is_(True), UserAddress.id != keep)
        .values(is_default=False)
    )


def create_address(session: Session, user_id: uuid.UUID, fields: dict[str, Any]) -> UserAddress:
    _lock_profile(session, user_id)
    has_any = session.scalar(select(func.count()).select_from(UserAddress).where(UserAddress.user_id == user_id))
    address = UserAddress(id=uuid.uuid4(), user_id=user_id, **fields)
    if not has_any:
        address.is_default = True  # the first address becomes the default
    if address.is_default:
        _clear_other_defaults(session, user_id, keep=address.id)
    session.add(address)
    session.commit()
    return address


def replace_address(session: Session, user_id: uuid.UUID, address_id: uuid.UUID, fields: dict[str, Any]) -> UserAddress:
    _lock_profile(session, user_id)
    address = get_owned_address(session, user_id, address_id, lock=True)
    for field, value in fields.items():
        setattr(address, field, value)
    if address.is_default:
        _clear_other_defaults(session, user_id, keep=address.id)
    session.commit()
    return address


def delete_address(session: Session, user_id: uuid.UUID, address_id: uuid.UUID) -> None:
    """Deleting the default leaves no default; the next POST/PUT with is_default sets one."""
    _lock_profile(session, user_id)
    address = get_owned_address(session, user_id, address_id, lock=True)
    session.delete(address)
    session.commit()
