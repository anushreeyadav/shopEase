"""SQLAlchemy ORM model for a user's saved addresses.

alembic/env.py imports this module so that Alembic can detect its tables.
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.core.phone_utils import normalize_phone_number
from app.database.connection import Base

if TYPE_CHECKING:
    from app.models.user_model import UserProfile


class AddressType(str, enum.Enum):
    HOME = "HOME"
    OFFICE = "OFFICE"
    OTHER = "OTHER"


class UserAddress(Base):
    """A delivery address that belongs to one user profile.

    user_id is the local user_profiles.id, not the Authentication Service user ID.
    """

    __tablename__ = "user_addresses"
    __table_args__ = (
        # At most one default address per profile. default_marker is 1 for the default address
        # and NULL otherwise, and a unique index allows any number of NULLs. MySQL has no partial
        # unique index, so this generated column stands in for one.
        UniqueConstraint("user_id", "default_marker", name="uq_user_addresses_one_default_per_user"),
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        # Deleting a profile deletes its addresses (see UserProfile.addresses).
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        # Explicit index for the foreign key and for listing a user's addresses.
        index=True,
    )
    address_type: Mapped[AddressType] = mapped_column(
        Enum(AddressType, name="address_type", native_enum=False, create_constraint=True, length=20),
        nullable=False,
        default=AddressType.HOME,
        server_default=AddressType.HOME.value,
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)  # recipient's name
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    address_line_1: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line_2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(20), nullable=False)
    is_default: Mapped[bool] = mapped_column(
        # "0", not false(): MySQL reports a BOOLEAN default as 0, and this keeps autogenerate quiet.
        Boolean, nullable=False, default=False, server_default="0"
    )
    # Must not read user_id: MySQL forbids ON DELETE CASCADE on a column that a stored
    # generated column is computed from.
    default_marker: Mapped[int | None] = mapped_column(
        Integer, Computed("CASE WHEN is_default THEN 1 ELSE NULL END", persisted=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    user_profile: Mapped["UserProfile"] = relationship(back_populates="addresses")

    @validates("phone_number")
    def _normalize_phone_number(self, _key: str, value: str) -> str:
        # Schemas normalize already; this keeps every write path consistent.
        return normalize_phone_number(value)
