"""Business logic for stock levels and the inventory history.

Every stock change is an inventory transaction:
    IN   stock received   (stock_quantity += quantity)
    OUT  stock removed    (stock_quantity -= quantity; refused if it would go below 0)

One movement is one database transaction:
  1. SELECT ... FOR UPDATE locks the product row. A concurrent movement of the same product waits
     here until this one commits or rolls back, then reads the new stock. Movements of different
     products do not wait for each other.
  2. The stock check runs against that locked, current value.
  3. The new stock_quantity and its inventory_transactions row are written.
  4. COMMIT saves both. On any failure (insufficient stock, a database refusal, a lost
     connection) the transaction is rolled back, so neither is saved and the lock is released.

Initial stock of a new product is recorded the same way (record_movement, type IN, remarks
"Initial stock") inside the product's own create transaction. Product updates cannot change
stock_quantity at all, and app.models.stock_guard refuses any flush that changes it without a
matching history row.
"""

from sqlalchemy.exc import IntegrityError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.inventory_model import InventoryTransaction, TransactionType
from app.models.product_model import Product
from app.schemas.product_schema import MAX_STOCK
from app.services.errors import ConflictError, NotFoundError

INITIAL_STOCK_REMARKS = "Initial stock"


def _not_found() -> NotFoundError:
    return NotFoundError("Product not found")


def low_stock_threshold() -> int:
    return get_settings().low_stock_threshold


def is_low_stock(product: Product) -> bool:
    return product.stock_quantity <= low_stock_threshold()


def _locked_product(db: Session, product_id: int) -> Product:
    product = db.scalars(select(Product).where(Product.id == product_id).with_for_update()).one_or_none()
    if product is None:
        raise _not_found()
    return product


def record_movement(
    db: Session, product: Product, transaction_type: TransactionType, quantity: int, remarks: str | None
) -> InventoryTransaction:
    """Apply one stock movement to a product (already locked or just created) and add its history row.

    Does not commit: the caller commits, so the stock level and the history row are saved together.
    """
    if quantity <= 0:
        raise ValueError("quantity must be positive")  # schemas already enforce this
    previous = product.stock_quantity
    if transaction_type is TransactionType.IN:
        updated = previous + quantity
        if updated > MAX_STOCK:
            raise ConflictError("Stock would exceed the maximum allowed quantity")
    else:
        updated = previous - quantity
        if updated < 0:
            raise ConflictError(f"Insufficient stock: {previous} available, {quantity} requested")

    product.stock_quantity = updated
    transaction = InventoryTransaction(
        product_id=product.id,
        transaction_type=transaction_type,
        quantity=quantity,
        previous_stock=previous,
        updated_stock=updated,
        remarks=remarks,
    )
    db.add(transaction)
    return transaction


def _move(db: Session, product_id: int, transaction_type: TransactionType, quantity: int,
          remarks: str | None) -> tuple[InventoryTransaction, Product]:
    """Steps 1-4 of the module docstring. Nothing is saved unless everything succeeds."""
    try:
        product = _locked_product(db, product_id)
        transaction = record_movement(db, product, transaction_type, quantity, remarks)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # A CHECK constraint refused the row: the service's own checks should make this impossible.
        raise ConflictError("The stock change was refused by the database; nothing was changed") from exc
    except BaseException:
        db.rollback()  # releases the row lock; stock and history stay as they were
        raise
    return transaction, product


def stock_in(db: Session, product_id: int, quantity: int, remarks: str | None = None):
    """Add stock. Returns (transaction, product)."""
    return _move(db, product_id, TransactionType.IN, quantity, remarks)


def stock_out(db: Session, product_id: int, quantity: int, remarks: str | None = None):
    """Remove stock; refused with ConflictError if there is not enough. Returns (transaction, product)."""
    return _move(db, product_id, TransactionType.OUT, quantity, remarks)


def get_stock(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise _not_found()
    return product


def list_transactions(
    db: Session,
    product_id: int,
    *,
    offset: int = 0,
    limit: int = 20,
    transaction_type: TransactionType | None = None,
) -> tuple[list[InventoryTransaction], int]:
    """A product's history, newest first. Returns (items on the page, total matching)."""
    get_stock(db, product_id)  # 404 for an unknown product, rather than an empty list
    filters = [InventoryTransaction.product_id == product_id]
    if transaction_type is not None:
        filters.append(InventoryTransaction.transaction_type == transaction_type)

    total = db.scalar(select(func.count(InventoryTransaction.id)).where(*filters)) or 0
    items = db.scalars(
        select(InventoryTransaction)
        .where(*filters)
        # Served by ix_inventory_transactions_product_id_created_at; id breaks ties within a second.
        .order_by(InventoryTransaction.created_at.desc(), InventoryTransaction.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(items), total


def list_low_stock(db: Session) -> list[Product]:
    """Active products at or below LOW_STOCK_THRESHOLD, lowest stock first."""
    statement = (
        select(Product)
        .where(Product.is_active.is_(True), Product.stock_quantity <= low_stock_threshold())
        .order_by(Product.stock_quantity, Product.id)
    )
    return list(db.scalars(statement))
