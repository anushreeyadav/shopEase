"""Request and response schemas for stock levels and inventory transactions."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models.inventory_model import REMARKS_LENGTH, TransactionType
from app.schemas.common_schema import Page, PageQuery, SingleLineText
from app.schemas.product_schema import MAX_STOCK

# Strict: a JSON whole number. "5", 5.0 and true are refused rather than converted.
Quantity = Annotated[int, Field(strict=True, ge=1, le=MAX_STOCK, description="Whole number, at least 1",
                                examples=[20])]
Remarks = Annotated[str, Field(min_length=1, max_length=REMARKS_LENGTH), SingleLineText]


class StockMovementRequest(BaseModel):
    """POST /api/inventory/{product_id}/stock-in and /stock-out."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    quantity: Quantity
    remarks: Remarks | None = Field(default=None, examples=["Delivery from supplier, invoice 4471"])


class StockLevelResponse(BaseModel):
    product_id: int
    sku: str
    name: str
    stock_quantity: int
    low_stock_threshold: int
    is_low_stock: bool


class InventoryTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    transaction_type: TransactionType
    quantity: int
    previous_stock: int
    updated_stock: int
    remarks: str | None
    created_at: datetime


class StockMovementResponse(BaseModel):
    """The recorded transaction and the product's new stock level."""

    transaction: InventoryTransactionResponse
    stock: StockLevelResponse


InventoryTransactionListResponse = Page[InventoryTransactionResponse]


class TransactionListQuery(PageQuery):
    """Query parameters of GET /api/inventory/{product_id}/history."""

    transaction_type: TransactionType | None = Field(default=None, description="Only IN or only OUT")
