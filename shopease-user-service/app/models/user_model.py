"""SQLAlchemy ORM model for user profiles.

alembic/env.py imports this module so that Alembic can detect its tables.
"""

import enum
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.core.phone_utils import normalize_phone_number
from app.database.connection import Base

if TYPE_CHECKING:
    from app.models.address_model import UserAddress


class Gender(str, enum.Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    OTHER = "OTHER"
    PREFER_NOT_TO_SAY = "PREFER_NOT_TO_SAY"


class UserProfile(Base):
    """Profile data for a user registered in the Authentication Service.

    Holds no credentials: no email, password, token, or login field. Those stay in the
    Authentication Service.

    auth_user_id is the user's ID in the Authentication Service, as returned by its
    verify-token endpoint. It is not a foreign key: the users table lives in that
    service's own database.

    is_active is this service's own flag, used to deactivate a profile without deleting it.
    It is unrelated to the user's active status in the Authentication Service, which is
    checked separately on every request.
    """

    __tablename__ = "user_profiles"
    # Load database-generated values on flush. Sessions may be closed before they are read.
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Unique constraint uq_user_profiles_auth_user_id. MySQL backs it with a unique index,
    # which also serves the lookup by auth_user_id on every request.
    auth_user_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    # VARCHAR + CHECK constraint, not a MySQL ENUM, so new values need no column rebuild.
    gender: Mapped[Gender | None] = mapped_column(
        Enum(Gender, name="gender", native_enum=False, create_constraint=True, length=20),
        nullable=True,
    )
    profile_image: Mapped[str | None] = mapped_column(String(500), nullable=True)  # image URL
    is_active: Mapped[bool] = mapped_column(
        # "1", not true(): MySQL reports a BOOLEAN default as 1, and this keeps autogenerate quiet.
        Boolean, nullable=False, default=True, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    addresses: Mapped[list["UserAddress"]] = relationship(
        back_populates="user_profile",
        # Addresses cannot exist without their profile: removing one from this list deletes it.
        cascade="all, delete-orphan",
        # Deleting a profile leaves the address rows to the database's ON DELETE CASCADE,
        # instead of loading them first.
        passive_deletes=True,
        order_by="UserAddress.id",
    )

    @validates("phone_number")
    def _normalize_phone_number(self, _key: str, value: str | None) -> str | None:
        # Schemas normalize already; this keeps every write path consistent.
        return None if value is None else normalize_phone_number(value)
