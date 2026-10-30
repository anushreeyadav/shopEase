"""payment_db tables: payment attempts, their status audit trail, and refunds.

Never stored: card numbers (PAN), CVV/CVC, PINs or provider secret keys. Only the
provider's reference, the card brand and the last four digits.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey, str_enum


class PaymentStatus(enum.StrEnum):
    """Transitions are in docs/service_communication.md §2 and enforced by the service."""

    INITIATED = "INITIATED"
    PROCESSING = "PROCESSING"  # provider outcome unknown; resolved by reconciliation
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class StatusSource(enum.StrEnum):
    API = "API"
    WEBHOOK = "WEBHOOK"
    RECONCILIATION = "RECONCILIATION"


class RefundStatus(enum.StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class Payment(UUIDPrimaryKey, Timestamps, Base):
    """One payment attempt. `order_id` and `user_id` are external IDs (no foreign keys)."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("provider", "provider_txn_ref"),
        CheckConstraint("amount > 0", name="amount_positive"),
        # active_order_id is set only while the payment is INITIATED, PROCESSING or SUCCEEDED,
        # and is unique: an order can never have two active payments.
        CheckConstraint(
            "active_order_id IS NULL OR active_order_id = order_id", name="active_order_matches"
        ),
        # Reconciliation scans PROCESSING payments by age.
        Index("ix_payments_status_updated_at", "status", "updated_at"),
        Index("ix_payments_status_next_reconcile_at", "status", "next_reconcile_at"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))  # ISO 4217
    status: Mapped[PaymentStatus] = mapped_column(
        str_enum(PaymentStatus, "status"), default=PaymentStatus.INITIATED
    )
    provider: Mapped[str] = mapped_column(String(32))  # "mock" until a real provider exists
    provider_txn_ref: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    # SHA-256 of the canonical request body: same key + different body -> 409.
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    active_order_id: Mapped[uuid.UUID | None] = mapped_column(unique=True)
    card_brand: Mapped[str | None] = mapped_column(String(20))
    card_last4: Mapped[str | None] = mapped_column(String(4))
    failure_reason: Mapped[str | None] = mapped_column(String(255))
    # When order_service acknowledged the result; NULL means the report must be retried.
    result_reported_at: Mapped[datetime | None]
    report_attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    next_report_at: Mapped[datetime | None] = mapped_column(index=True)
    # Unknown outcomes (PROCESSING) are re-checked with the provider on a bounded schedule.
    reconcile_attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    next_reconcile_at: Mapped[datetime | None]
    # Automatic handling stopped (schedule exhausted, or an inconsistent provider answer):
    # a person must resolve it. The payment stays active, so the order can't be charged again.
    needs_manual_review: Mapped[bool] = mapped_column(default=False, server_default=false())

    status_history: Mapped[list["PaymentStatusHistory"]] = relationship(back_populates="payment")
    refunds: Mapped[list["Refund"]] = relationship(back_populates="payment")


class PaymentStatusHistory(UUIDPrimaryKey, CreatedAt, Base):
    """Append-only record of status changes and verified provider events."""

    __tablename__ = "payment_status_history"

    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id"), index=True)
    from_status: Mapped[PaymentStatus | None] = mapped_column(
        str_enum(PaymentStatus, "from_status")
    )
    to_status: Mapped[PaymentStatus] = mapped_column(str_enum(PaymentStatus, "to_status"))
    source: Mapped[StatusSource] = mapped_column(str_enum(StatusSource, "source"))
    # Unique so a redelivered webhook is recorded only once (NULLs are allowed repeatedly).
    provider_event_id: Mapped[str | None] = mapped_column(String(128), unique=True)

    payment: Mapped[Payment] = relationship(back_populates="status_history")


class Refund(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "refunds"
    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)

    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[RefundStatus] = mapped_column(
        str_enum(RefundStatus, "status"), default=RefundStatus.PENDING
    )
    provider_refund_ref: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(String(255))
    # Idempotent refunds: a retried compensation or admin request reuses the same key.
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)

    payment: Mapped[Payment] = relationship(back_populates="refunds")
