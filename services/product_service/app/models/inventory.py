"""product_db stock tables: current levels, reservations for orders, and the movement log."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey, str_enum, utcnow


class ReservationStatus(enum.StrEnum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"  # payment succeeded; stock deducted
    RELEASED = "RELEASED"  # order cancelled; stock returned
    EXPIRED = "EXPIRED"  # payment window passed; stock returned by the expiry job


class MovementReason(enum.StrEnum):
    RESTOCK = "RESTOCK"
    RESERVE = "RESERVE"
    CONFIRM = "CONFIRM"
    RELEASE = "RELEASE"
    ADJUST = "ADJUST"


class Inventory(Base):
    """Current stock per product. `version` gives optimistic locking on concurrent updates."""

    __tablename__ = "inventory"
    __table_args__ = (
        CheckConstraint("quantity_on_hand >= 0", name="on_hand_non_negative"),
        CheckConstraint("quantity_reserved >= 0", name="reserved_non_negative"),
        CheckConstraint("quantity_reserved <= quantity_on_hand", name="reserved_within_on_hand"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), primary_key=True)
    quantity_on_hand: Mapped[int] = mapped_column(default=0)
    quantity_reserved: Mapped[int] = mapped_column(default=0)
    version: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __mapper_args__ = {"version_id_col": version}


class StockReservation(UUIDPrimaryKey, Timestamps, Base):
    """Stock held for an order. Unique per (order_id, product_id), so retries are idempotent.

    `order_id` belongs to order_service: an indexed external ID, no foreign key.
    """

    __tablename__ = "stock_reservations"
    __table_args__ = (
        UniqueConstraint("order_id", "product_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        Index("ix_stock_reservations_status_expires_at", "status", "expires_at"),
    )

    order_id: Mapped[uuid.UUID]
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    quantity: Mapped[int]
    status: Mapped[ReservationStatus] = mapped_column(
        str_enum(ReservationStatus, "status"), default=ReservationStatus.RESERVED
    )
    expires_at: Mapped[datetime]


class InventoryMovement(UUIDPrimaryKey, CreatedAt, Base):
    """Append-only audit record of every stock change (never updated or deleted).

    | reason  | quantity_change (on hand) | reserved_change |
    |---------|---------------------------|-----------------|
    | RESTOCK | +n                        | 0               |
    | ADJUST  | +/-n                      | 0               |
    | RESERVE | 0                         | +n              |
    | RELEASE | 0                         | -n              |
    | CONFIRM | -n                        | -n              |
    """

    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint("quantity_change <> 0 OR reserved_change <> 0", name="has_change"),
        Index("ix_inventory_movements_product_id_created_at", "product_id", "created_at"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    # Signed change to quantity_on_hand. Named quantity_change, not `change`, because CHANGE
    # is a reserved word in MySQL.
    quantity_change: Mapped[int]
    reserved_change: Mapped[int] = mapped_column(default=0, server_default="0")
    # Levels right after this change, so the history can be audited row by row.
    on_hand_after: Mapped[int | None]
    reserved_after: Mapped[int | None]
    reason: Mapped[MovementReason] = mapped_column(str_enum(MovementReason, "reason"))
    # External reference, e.g. the order_id for RESERVE/CONFIRM/RELEASE. No foreign key.
    reference_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    # Who made the change: an admin's user ID, a service such as "svc:order", or "system:expiry".
    actor: Mapped[str] = mapped_column(String(64), default="system", server_default="system")
    note: Mapped[str | None] = mapped_column(String(255))
