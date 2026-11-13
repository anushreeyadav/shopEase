"""ORM models. Importing this package registers every table on Base.metadata."""

from app.models.category_model import Category
from app.models.inventory_model import InventoryTransaction, TransactionType
from app.models.product_model import Product
from app.models import stock_guard  # noqa: F401  (registers the stock-change check on every session)

__all__ = ["Category", "InventoryTransaction", "Product", "TransactionType"]
