"""order_db tables: orders, their line items and the status audit trail."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Numeric, String, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey, str_enum, utcnow


class OrderStatus(enum.StrEnum):
    """Transitions are in docs/service_communication.md §2 and enforced by the service."""

    PENDING = "PENDING"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    PAID = "PAID"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PaymentStatus(enum.StrEnum):
    """Latest payment outcome reported by payment_service (the order status stays authoritative)."""

    NONE = "NONE"
    PROCESSING = "PROCESSING"  # outcome unknown; payment_service is reconciling
    FAILED = "FAILED"  # declined; the customer may retry until payment_due_by
    SUCCEEDED = "SUCCEEDED"
    REFUNDED = "REFUNDED"


class Order(UUIDPrimaryKey, Timestamps, Base):
    """Order header. `user_id` and `payment_id` are external IDs (no foreign keys)."""

    __tablename__ = "orders"
    __table_args__ = (
        # Idempotency-Key is scoped to the user who sent it.
        UniqueConstraint("user_id", "idempotency_key"),
        CheckConstraint("total_amount >= 0", name="total_amount_non_negative"),
        Index("ix_orders_user_id_created_at", "user_id", "created_at"),
        # The expiry job looks for AWAITING_PAYMENT orders past payment_due_by.
        Index("ix_orders_status_payment_due_by", "status", "payment_due_by"),
        # The recovery job looks for PENDING orders abandoned mid-checkout.
        Index("ix_orders_status_created_at", "status", "created_at"),
    )

    user_id: Mapped[uuid.UUID]
    status: Mapped[OrderStatus] = mapped_column(
        str_enum(OrderStatus, "status"), default=OrderStatus.PENDING
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))  # ISO 4217
    # Copied from user_service at checkout, so later address edits don't change the order.
    shipping_address_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    # SHA-256 of the canonical request body: same key + different body -> 409.
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    payment_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    payment_due_by: Mapped[datetime | None]
    payment_status: Mapped[PaymentStatus] = mapped_column(
        str_enum(PaymentStatus, "payment_status"), default=PaymentStatus.NONE, server_default="NONE"
    )
    # Why the order was cancelled, e.g. OUT_OF_STOCK, PAYMENT_TIMEOUT, CUSTOMER_CANCELLED.
    cancel_reason: Mapped[str | None] = mapped_column(String(64))
    # Stock may still be held at product_service and must be released by the recovery job.
    release_pending: Mapped[bool] = mapped_column(default=False, server_default=false(), index=True)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order")
    status_history: Mapped[list["OrderStatusHistory"]] = relationship(back_populates="order")


class OrderItem(UUIDPrimaryKey, Base):
    """Line item with name and price snapshots (ADR-07). `product_id` is an external ID."""

    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "product_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price_snapshot >= 0", name="unit_price_non_negative"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(index=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(200))
    unit_price_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    quantity: Mapped[int]

    order: Mapped[Order] = relationship(back_populates="items")


class OrderStatusHistory(UUIDPrimaryKey, Base):
    """Append-only record of every status change."""

    __tablename__ = "order_status_history"
    __table_args__ = (Index("ix_order_status_history_order_id_changed_at", "order_id", "changed_at"),)

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"))
    from_status: Mapped[OrderStatus | None] = mapped_column(str_enum(OrderStatus, "from_status"))
    to_status: Mapped[OrderStatus] = mapped_column(str_enum(OrderStatus, "to_status"))
    # A user ID, a service identity such as "svc:payment", or "system" for background jobs.
    changed_by: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(String(255))
    changed_at: Mapped[datetime] = mapped_column(default=utcnow)

    order: Mapped[Order] = relationship(back_populates="status_history")
