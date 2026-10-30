"""Pydantic request/response schemas for product_service (rest_api_notes.md §3.4, Part 4).

Money is a Decimal with two places; Pydantic serializes it as a string ("2499.00").
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, computed_field, model_validator

from app.models import MovementReason, ProductStatus, ReservationStatus

MAX_STOCK = 1_000_000
T = TypeVar("T")


def _clean_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("must not contain control characters")
    return value


Name = Annotated[str, Field(min_length=1, max_length=200), AfterValidator(_clean_text)]
CategoryName = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(_clean_text)]
Description = Annotated[str, Field(max_length=5000)]
# Stored upper-case so uniqueness doesn't depend on the database collation.
Sku = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^\s*[A-Za-z0-9][A-Za-z0-9._-]*\s*$"),
    AfterValidator(lambda v: v.strip().upper()),
]
Price = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class Page(BaseModel, Generic[T]):
    """Pagination envelope (rest_api_notes.md §1.6)."""

    items: list[T]
    total: int
    limit: int
    offset: int


# --- Categories ------------------------------------------------------------------------


class CategoryCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'name': 'Running Shoes', 'parent_id': None}]}, extra="forbid")

    name: CategoryName
    parent_id: uuid.UUID | None = None


class CategoryUpdate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'name': 'Trail Running Shoes'}]}, extra="forbid")

    name: CategoryName | None = None
    parent_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def name_not_null(self):
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        return self


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category_id: uuid.UUID = Field(validation_alias="id")
    name: str
    parent_id: uuid.UUID | None


class CategoryRef(BaseModel):
    category_id: uuid.UUID
    name: str


# --- Products --------------------------------------------------------------------------


class ProductCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'sku': 'SHOE-TRAIL-01', 'name': 'Trail Running Shoe', 'description': 'Grippy outsole.', 'category_id': None, 'price': '2499.00', 'currency': 'INR', 'initial_stock': 25}]}, extra="forbid")

    sku: Sku
    name: Name
    description: Description | None = None
    category_id: uuid.UUID | None = None
    price: Price
    currency: Currency = "INR"
    initial_stock: int = Field(default=0, ge=0, le=MAX_STOCK)


class ProductUpdate(BaseModel):
    """PATCH body: only the fields sent change. The SKU is immutable; status ARCHIVED deactivates."""

    model_config = ConfigDict(json_schema_extra={"examples": [{'price': '2299.00', 'status': 'ACTIVE'}]}, extra="forbid")

    name: Name | None = None
    description: Description | None = None
    category_id: uuid.UUID | None = None
    price: Price | None = None
    currency: Currency | None = None
    status: ProductStatus | None = None

    @model_validator(mode="after")
    def required_fields_not_null(self):
        for field in ("name", "price", "currency", "status"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class ProductSummary(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    price: Decimal
    currency: str
    category_id: uuid.UUID | None
    status: ProductStatus
    in_stock: bool


class ProductDetail(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    description: str | None
    price: Decimal
    currency: str
    category: CategoryRef | None
    available_quantity: int
    status: ProductStatus
    created_at: datetime
    updated_at: datetime


ProductSort = Literal["price", "-price", "name", "-name", "created_at", "-created_at"]


# --- Inventory ---------------------------------------------------------------------------


class InventoryAdjust(BaseModel):
    """Admin stock change: RESTOCK adds stock; ADJUST corrects it up or down (counts, damage)."""

    model_config = ConfigDict(json_schema_extra={"examples": [{'quantity_change': 10, 'reason': 'RESTOCK', 'note': 'Purchase order PO-1001'}]}, extra="forbid")

    quantity_change: int = Field(ge=-MAX_STOCK, le=MAX_STOCK)
    reason: Literal[MovementReason.RESTOCK, MovementReason.ADJUST]
    note: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def check_change(self):
        if self.quantity_change == 0:
            raise ValueError("quantity_change must not be 0")
        if self.reason is MovementReason.RESTOCK and self.quantity_change < 0:
            raise ValueError("RESTOCK must add stock; use ADJUST to remove it")
        return self


class InventoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: uuid.UUID
    quantity_on_hand: int
    quantity_reserved: int
    version: int

    @computed_field
    @property
    def quantity_available(self) -> int:
        return self.quantity_on_hand - self.quantity_reserved


class MovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    movement_id: uuid.UUID = Field(validation_alias="id")
    reason: MovementReason
    quantity_change: int
    reserved_change: int
    on_hand_after: int | None
    reserved_after: int | None
    reference_id: uuid.UUID | None
    actor: str
    note: str | None
    created_at: datetime


# --- Internal: price check and reservations (rest_api_notes.md Part 4) --------------------


def _unique(ids: list[uuid.UUID]) -> list[uuid.UUID]:
    if len(set(ids)) != len(ids):
        raise ValueError("product IDs must be unique")
    return ids


class PriceCheckRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'product_ids': ['9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c61']}]}, extra="forbid")

    product_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=100), AfterValidator(_unique)]


class PriceCheckItem(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    price: Decimal
    currency: str
    status: ProductStatus
    available_quantity: int
    orderable: bool


class PriceCheckResponse(BaseModel):
    items: list[PriceCheckItem]
    missing: list[uuid.UUID]


class ReservationItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    quantity: int = Field(ge=1, le=1000)


class ReservationRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'order_id': '5e7a9c1b-3d5f-4e7a-9b1c-3d5e7f9a1b21', 'items': [{'product_id': '9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c61', 'quantity': 2}], 'ttl_seconds': 900}]}, extra="forbid")

    order_id: uuid.UUID
    items: list[ReservationItemIn] = Field(min_length=1, max_length=50)
    ttl_seconds: int | None = Field(default=None, ge=60, le=7200)

    @model_validator(mode="after")
    def unique_products(self):
        _unique([item.product_id for item in self.items])
        return self


class ReservationItemOut(BaseModel):
    product_id: uuid.UUID
    quantity: int
    status: ReservationStatus


class ReservationResponse(BaseModel):
    order_id: uuid.UUID
    status: ReservationStatus
    expires_at: datetime
    items: list[ReservationItemOut]
