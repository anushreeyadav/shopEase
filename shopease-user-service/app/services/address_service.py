"""Business logic for user addresses. No HTTP code here: routers translate these errors.

Ownership: every function takes the caller's auth_user_id, finds that user's active profile,
and looks addresses up by both address ID and that profile's ID. An address that belongs to
someone else is therefore reported exactly like one that does not exist (AddressNotFoundError).
The profile must exist and be active; otherwise the user_service profile errors are raised.

Default address: a user has at most one default address.
- The first address always becomes the default.
- Creating an address with is_default, or calling set_default_address, clears the old default.
- Deleting the default makes the oldest remaining address the default.
The database enforces the rule too (uq_user_addresses_one_default_per_user), so the old
default is cleared and flushed before the new one is set.

Transactions: each write runs in _transaction, which commits at the end or rolls back
everything if any step fails. Each write first locks the owning profile row
(SELECT ... FOR UPDATE), so concurrent writes for one user run one after another and can never
create two defaults. Every write takes the profile lock before any address lock, so they
cannot deadlock each other.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.address_model import UserAddress
from app.schemas.address_schema import AddressCreate, AddressFields, AddressReplace
from app.services.user_service import get_active_profile

_EDITABLE_FIELDS = tuple(AddressFields.model_fields)


class AddressNotFoundError(Exception):
    """No address with this ID belongs to the caller. Also used when it belongs to someone else."""


class DefaultAddressNotFoundError(Exception):
    """The caller has no default address, because they have no addresses."""


@contextmanager
def _transaction(db: Session) -> Iterator[None]:
    try:
        yield
        db.commit()
    except Exception:
        db.rollback()
        raise


def _get_owned_address(db: Session, profile_id: int, address_id: int) -> UserAddress:
    address = db.scalars(
        select(UserAddress).where(UserAddress.id == address_id, UserAddress.user_id == profile_id)
    ).one_or_none()
    if address is None:
        raise AddressNotFoundError
    return address


def _current_default(db: Session, profile_id: int) -> UserAddress | None:
    return db.scalars(
        select(UserAddress).where(UserAddress.user_id == profile_id, UserAddress.is_default.is_(True))
    ).one_or_none()


def _clear_default(db: Session, profile_id: int) -> None:
    current = _current_default(db, profile_id)
    if current is not None:
        current.is_default = False
        db.flush()  # before a new default is set, or the unique key would see two


def list_addresses(db: Session, auth_user_id: int) -> list[UserAddress]:
    profile = get_active_profile(db, auth_user_id)
    return list(db.scalars(
        select(UserAddress)
        .where(UserAddress.user_id == profile.id)
        .order_by(UserAddress.is_default.desc(), UserAddress.id)
    ))


def get_address(db: Session, auth_user_id: int, address_id: int) -> UserAddress:
    profile = get_active_profile(db, auth_user_id)
    return _get_owned_address(db, profile.id, address_id)


def get_default_address(db: Session, auth_user_id: int) -> UserAddress:
    profile = get_active_profile(db, auth_user_id)
    address = _current_default(db, profile.id)
    if address is None:
        raise DefaultAddressNotFoundError
    return address


def create_address(db: Session, auth_user_id: int, data: AddressCreate) -> UserAddress:
    with _transaction(db):
        profile = get_active_profile(db, auth_user_id, for_update=True)
        make_default = data.is_default or _current_default(db, profile.id) is None
        if make_default:
            _clear_default(db, profile.id)
        address = UserAddress(
            user_id=profile.id, is_default=make_default, **data.model_dump(include=set(_EDITABLE_FIELDS))
        )
        db.add(address)
    return address


def replace_address(db: Session, auth_user_id: int, address_id: int, data: AddressReplace) -> UserAddress:
    with _transaction(db):
        profile = get_active_profile(db, auth_user_id, for_update=True)
        address = _get_owned_address(db, profile.id, address_id)
        # Every editable field is written; is_default is left as it is.
        for field in _EDITABLE_FIELDS:
            setattr(address, field, getattr(data, field))
    return address


def delete_address(db: Session, auth_user_id: int, address_id: int) -> None:
    with _transaction(db):
        profile = get_active_profile(db, auth_user_id, for_update=True)
        address = _get_owned_address(db, profile.id, address_id)
        was_default = address.is_default
        db.delete(address)
        db.flush()
        if was_default:
            oldest = db.scalars(
                select(UserAddress).where(UserAddress.user_id == profile.id).order_by(UserAddress.id).limit(1)
            ).first()
            if oldest is not None:
                oldest.is_default = True


def set_default_address(db: Session, auth_user_id: int, address_id: int) -> UserAddress:
    with _transaction(db):
        profile = get_active_profile(db, auth_user_id, for_update=True)
        address = _get_owned_address(db, profile.id, address_id)
        if not address.is_default:
            _clear_default(db, profile.id)
            address.is_default = True
    return address
