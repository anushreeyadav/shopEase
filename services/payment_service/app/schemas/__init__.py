"""Pydantic request/response schemas for payment_service (rest_api_notes.md §3.6).

Money is a Decimal with two places; Pydantic serializes it as a string ("2499.00").
Responses never contain payment-method tokens or card data beyond brand and last four digits.
"""

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import PaymentStatus, RefundStatus, StatusSource

T = TypeVar("T")
_CARD_LIKE = re.compile(r"\d{12,}")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class PaymentCreate(BaseModel):
    """The amount always comes from order_service. `expected_amount`/`currency`, if sent, must
    match it exactly (protects against paying a total the customer didn't see)."""

    model_config = ConfigDict(json_schema_extra={"examples": [{'order_id': '5e7a9c1b-3d5f-4e7a-9b1c-3d5e7f9a1b21', 'payment_method_token': 'mock_tok_success', 'expected_amount': '2499.00', 'currency': 'INR'}]}, extra="forbid")

    order_id: uuid.UUID
    # Opaque token from the provider's client-side SDK. Never a card number.
    payment_method_token: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_\-]+$")
    expected_amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    @field_validator("payment_method_token")
    @classmethod
    def no_card_numbers(cls, value: str) -> str:
        if _CARD_LIKE.search(value):
            raise ValueError("card numbers are not accepted; send the provider's payment-method token")
        return value


class PaymentMethodRead(BaseModel):
    type: str = "card"
    brand: str | None
    last4: str | None


class RefundRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    refund_id: uuid.UUID = Field(validation_alias="id")
    amount: Decimal
    status: RefundStatus
    reason: str | None
    provider_reference: str | None = Field(validation_alias="provider_refund_ref")
    created_at: datetime


class StatusEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: PaymentStatus | None
    to_status: PaymentStatus
    source: StatusSource
    created_at: datetime


class PaymentRead(BaseModel):
    payment_id: uuid.UUID
    order_id: uuid.UUID
    status: PaymentStatus
    amount: Decimal
    currency: str
    provider: str
    payment_method: PaymentMethodRead | None
    provider_reference: str | None
    failure_reason: str | None
    requires_review: bool
    refunds: list[RefundRead]
    status_history: list[StatusEventRead]
    created_at: datetime
    updated_at: datetime


class PaymentSummary(BaseModel):
    payment_id: uuid.UUID
    order_id: uuid.UUID
    status: PaymentStatus
    amount: Decimal
    currency: str
    created_at: datetime


class RefundCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'amount': '500.00', 'reason': 'Damaged item'}]}, extra="forbid")

    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2,
                                   description="Omit to refund the remaining amount")
    reason: str | None = Field(default=None, max_length=255)
