"""Pydantic request/response schemas for order_service (rest_api_notes.md §3.5, Part 4).

Money is a Decimal with two places; Pydantic serializes it as a string ("2499.00").
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import OrderStatus, PaymentStatus

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Pagination envelope (rest_api_notes.md §1.6)."""

    items: list[T]
    total: int
    limit: int
    offset: int


class OrderItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    quantity: int = Field(ge=1, le=100)


class OrderCreate(BaseModel):
    """Prices and totals are never accepted from the client (extra fields are rejected)."""

    model_config = ConfigDict(json_schema_extra={"examples": [{'items': [{'product_id': '9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c61', 'quantity': 1}], 'shipping_address_id': '7a1e4b2c-5d6f-4a8b-9c0d-2e3f4a5b6c71'}]}, extra="forbid")

    items: list[OrderItemCreate] = Field(min_length=1, max_length=50)
    shipping_address_id: uuid.UUID

    @model_validator(mode="after")
    def unique_products(self):
        ids = [item.product_id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("each product may appear only once; combine the quantities")
        return self


class OrderItemRead(BaseModel):
    product_id: uuid.UUID
    name: str
    unit_price: Decimal
    quantity: int
    line_total: Decimal


class StatusChangeRead(BaseModel):
    from_status: OrderStatus | None
    to_status: OrderStatus
    reason: str | None
    changed_at: datetime


class OrderRead(BaseModel):
    order_id: uuid.UUID
    user_id: uuid.UUID
    status: OrderStatus
    payment_status: PaymentStatus
    items: list[OrderItemRead]
    total_amount: Decimal
    currency: str
    shipping_address: dict[str, Any]
    payment_id: uuid.UUID | None
    payment_due_by: datetime | None
    cancel_reason: str | None
    status_history: list[StatusChangeRead]
    created_at: datetime
    updated_at: datetime


class OrderSummary(BaseModel):
    order_id: uuid.UUID
    status: OrderStatus
    payment_status: PaymentStatus
    total_amount: Decimal
    currency: str
    item_count: int
    created_at: datetime


class StatusUpdate(BaseModel):
    """Admin fulfilment. Cancellation has its own endpoint; PAID comes only from payments."""

    model_config = ConfigDict(json_schema_extra={"examples": [{'status': 'SHIPPED'}]}, extra="forbid")

    status: Literal[OrderStatus.SHIPPED, OrderStatus.DELIVERED]


# --- Internal: payment_service (rest_api_notes.md Part 4) ---------------------------------


class PayableRead(BaseModel):
    order_id: uuid.UUID
    user_id: uuid.UUID
    status: OrderStatus
    payment_status: PaymentStatus
    payable: bool
    amount: Decimal
    currency: str
    payment_due_by: datetime | None


class PaymentResult(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'payment_id': '8c0e2a4b-6d8f-4a0c-8e2b-4d6f8a0c2e41', 'outcome': 'SUCCEEDED', 'reason': None}]}, extra="forbid")

    payment_id: uuid.UUID
    outcome: Literal["SUCCEEDED", "FAILED", "PROCESSING", "REFUNDED"]
    reason: str | None = Field(default=None, max_length=255)


class PaymentResultRead(BaseModel):
    order_id: uuid.UUID
    status: OrderStatus
    payment_status: PaymentStatus
