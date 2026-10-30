"""user_db tables: profiles and delivery addresses."""

import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class UserProfile(Timestamps, Base):
    """One row per user, created on first access (ADR-09).

    `user_id` is the auth_service user ID taken from the verified JWT `sub`. It is an
    external identifier: there is deliberately no foreign key to auth_db.
    """

    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    full_name: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(32))
    contact_email: Mapped[str | None] = mapped_column(String(254))

    addresses: Mapped[list["UserAddress"]] = relationship(
        back_populates="profile", passive_deletes=True
    )


class UserAddress(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "user_addresses"
    # "At most one default address per user" is enforced by the service in the same
    # transaction (MySQL has no partial unique index). The index serves that lookup.
    __table_args__ = (Index("ix_user_addresses_user_id_is_default", "user_id", "is_default"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_profiles.user_id", ondelete="CASCADE")
    )
    label: Mapped[str | None] = mapped_column(String(50))
    line1: Mapped[str] = mapped_column(String(200))
    line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str] = mapped_column(String(20))
    country: Mapped[str] = mapped_column(String(2))  # ISO 3166-1 alpha-2
    is_default: Mapped[bool] = mapped_column(default=False)

    profile: Mapped[UserProfile] = relationship(back_populates="addresses")
