"""HTTP layer for stock levels and inventory history: request handling only, no business logic.

Every inventory route needs the ADMIN role: stock-in and stock-out change stock, and the history
and low-stock report are internal. Customers see stock only as stock_quantity and in_stock on the
product endpoints. The workflow (locking, one transaction per movement) is in
app/services/inventory_service.py.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.core.security import MAX_DB_INT, require_admin
from app.database.connection import get_db
from app.models.product_model import Product
from app.routers.responses import ADMIN_ERRORS, BAD_BODY, CONFLICT, INVALID, NOT_FOUND
from app.schemas.inventory_schema import (
    InventoryTransactionListResponse,
    InventoryTransactionResponse,
    StockLevelResponse,
    StockMovementRequest,
    StockMovementResponse,
    TransactionListQuery,
)
from app.services import inventory_service

router = APIRouter(prefix="/inventory", tags=["Inventory"], dependencies=[Depends(require_admin)])

ProductIdPath = Annotated[int, Path(ge=1, le=MAX_DB_INT, description="Product ID")]
MOVEMENT_ERRORS = {**ADMIN_ERRORS, **NOT_FOUND, **CONFLICT, **INVALID}


def _stock_level(product: Product) -> StockLevelResponse:
    return StockLevelResponse(
        product_id=product.id,
        sku=product.sku,
        name=product.name,
        stock_quantity=product.stock_quantity,
        low_stock_threshold=inventory_service.low_stock_threshold(),
        is_low_stock=inventory_service.is_low_stock(product),
    )


@router.get(
    "/low-stock",
    response_model=list[StockLevelResponse],
    summary="Low-stock report",
    description=(
        "Active products whose stock is **at or below** LOW_STOCK_THRESHOLD (setting, default 5), "
        "lowest stock first. Inactive products are left out: they are not for sale."
    ),
    responses=ADMIN_ERRORS,
)
def list_low_stock(db: Session = Depends(get_db)):
    return [_stock_level(product) for product in inventory_service.list_low_stock(db)]


@router.get(
    "/{product_id}",
    response_model=StockLevelResponse,
    summary="Get a product's current stock",
    description="Current stock_quantity and whether it is at or below LOW_STOCK_THRESHOLD. "
                "Inactive products are included (stock still exists).",
    responses={**ADMIN_ERRORS, **NOT_FOUND, **INVALID},
)
def read_stock(product_id: ProductIdPath, db: Session = Depends(get_db)):
    return _stock_level(inventory_service.get_stock(db, product_id))


@router.post(
    "/{product_id}/stock-in",
    response_model=StockMovementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add stock (IN transaction)",
    description=(
        "Increases stock by `quantity` (a whole number, at least 1) and records an IN transaction "
        "with the previous and new stock, the remarks and the time. Both are saved in one database "
        "transaction with the product row locked, or neither is."
    ),
    responses={**BAD_BODY, **MOVEMENT_ERRORS},
)
def stock_in(product_id: ProductIdPath, request: StockMovementRequest, db: Session = Depends(get_db)):
    transaction, product = inventory_service.stock_in(db, product_id, request.quantity, request.remarks)
    return StockMovementResponse(
        transaction=InventoryTransactionResponse.model_validate(transaction), stock=_stock_level(product)
    )


@router.post(
    "/{product_id}/stock-out",
    response_model=StockMovementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Remove stock (OUT transaction)",
    description=(
        "Decreases stock by `quantity` and records an OUT transaction, in one database transaction "
        "with the product row locked. If the product has less stock than requested, the answer is "
        "409 `Insufficient stock: N available, M requested` and nothing changes: stock never goes "
        "below 0."
    ),
    responses={**BAD_BODY, **MOVEMENT_ERRORS},
)
def stock_out(product_id: ProductIdPath, request: StockMovementRequest, db: Session = Depends(get_db)):
    transaction, product = inventory_service.stock_out(db, product_id, request.quantity, request.remarks)
    return StockMovementResponse(
        transaction=InventoryTransactionResponse.model_validate(transaction), stock=_stock_level(product)
    )


@router.get(
    "/{product_id}/history",
    response_model=InventoryTransactionListResponse,
    summary="A product's stock transaction history",
    description=(
        "Every stock movement of the product, newest first, including its initial stock. `total` "
        "is the number of transactions; the pages together return all of them (`page_size` up to "
        "100). `transaction_type=IN` or `OUT` limits it to one type."
    ),
    responses={**ADMIN_ERRORS, **NOT_FOUND, **INVALID},
)
def read_history(
    product_id: ProductIdPath,
    query: Annotated[TransactionListQuery, Query()],
    db: Session = Depends(get_db),
):
    items, total = inventory_service.list_transactions(
        db, product_id, offset=query.offset, limit=query.page_size, transaction_type=query.transaction_type
    )
    return InventoryTransactionListResponse.build(
        [InventoryTransactionResponse.model_validate(item) for item in items], total, query
    )
