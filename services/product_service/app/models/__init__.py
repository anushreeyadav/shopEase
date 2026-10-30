"""product_service models. Importing this package registers every table on Base.metadata."""

from app.models.base import Base
from app.models.catalog import Category, Product, ProductStatus
from app.models.inventory import (
    Inventory,
    InventoryMovement,
    MovementReason,
    ReservationStatus,
    StockReservation,
)

__all__ = [
    "Base",
    "Category",
    "Inventory",
    "InventoryMovement",
    "MovementReason",
    "Product",
    "ProductStatus",
    "ReservationStatus",
    "StockReservation",
]
