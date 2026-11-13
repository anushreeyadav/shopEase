"""Stock never changes without a history row.

A before_flush hook on every SQLAlchemy session checks each product whose stock_quantity is about
to be written:

- a new product must start at 0 (initial stock is recorded afterwards as an IN transaction);
- a changed product must have new inventory_transactions rows in the same flush that lead from
  the old value to the new one: the first starts at the old stock, each starts where the previous
  ended, and the last ends at the new stock.

Otherwise the flush is refused with StockChangeWithoutTransaction, the caller rolls back, and
nothing is saved. This catches programming mistakes, for example a future endpoint that sets
product.stock_quantity directly. The API already refuses stock_quantity in every product request.

It guards the application's own writes. A manual SQL UPDATE run directly against the database
bypasses it; stock corrections must therefore also be made through stock-in or stock-out.
"""

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.models.inventory_model import InventoryTransaction, TransactionType
from app.models.product_model import Product


class StockChangeWithoutTransaction(RuntimeError):
    """stock_quantity was changed without matching inventory transactions."""


def _chain_matches(old: int, new: int, movements: list[InventoryTransaction]) -> bool:
    stock = old
    for movement in movements:
        signed = movement.quantity if movement.transaction_type == TransactionType.IN else -movement.quantity
        if movement.previous_stock != stock or movement.updated_stock != stock + signed:
            return False
        stock = movement.updated_stock
    return stock == new


@event.listens_for(Session, "before_flush")
def _stock_changes_need_transactions(session: Session, _flush_context, _instances) -> None:
    new_movements: dict[int, list[InventoryTransaction]] = {}
    for obj in session.new:
        if isinstance(obj, InventoryTransaction):
            product_id = obj.product_id if obj.product_id is not None else getattr(obj.product, "id", None)
            new_movements.setdefault(product_id, []).append(obj)

    for obj in session.new:
        if isinstance(obj, Product) and obj.stock_quantity not in (None, 0):
            raise StockChangeWithoutTransaction(
                "A new product must start with stock 0; record initial stock as an IN transaction")

    for obj in session.dirty:
        if not isinstance(obj, Product):
            continue
        history = inspect(obj).attrs.stock_quantity.history
        if not history.has_changes():
            continue
        old = history.deleted[0] if history.deleted else None
        new = obj.stock_quantity
        # Movements are added in the order they happen; their ids are not assigned yet.
        if old is None or not _chain_matches(old, new, new_movements.get(obj.id, [])):
            raise StockChangeWithoutTransaction(
                f"stock_quantity of product {obj.id} changed from {old} to {new} without a matching "
                "inventory transaction")
