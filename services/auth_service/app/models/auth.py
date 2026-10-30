"""auth_db tables: login identities, refresh tokens and internal service clients."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey, str_enum


class Role(enum.StrEnum):
    CUSTOMER = "customer"
    ADMIN = "admin"


class UserStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class AuthUser(UUIDPrimaryKey, Timestamps, Base):
    """Login identity. `id` is the JWT `sub` that other services store as `user_id`."""

    __tablename__ = "auth_users"
    __table_args__ = (
        CheckConstraint("failed_login_attempts >= 0", name="failed_login_attempts_non_negative"),
    )

    # Stored lower-cased by the service, so uniqueness is case-insensitive in practice.
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(str_enum(Role, "role"), default=Role.CUSTOMER)
    status: Mapped[UserStatus] = mapped_column(
        str_enum(UserStatus, "status"), default=UserStatus.ACTIVE
    )
    failed_login_attempts: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None]

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", passive_deletes=True
    )


class RefreshToken(UUIDPrimaryKey, CreatedAt, Base):
    """Refresh tokens are stored only as a SHA-256 hash; rotation links old to new."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("auth_users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    revoked_at: Mapped[datetime | None]
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"), index=True
    )

    user: Mapped[AuthUser] = relationship(back_populates="refresh_tokens")


class ServiceClient(Timestamps, Base):
    """Internal service identity for service tokens (ADR-08), e.g. client_id "svc:order"."""

    __tablename__ = "service_clients"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    secret_hash: Mapped[str] = mapped_column(String(255))
    allowed_scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(default=True)
