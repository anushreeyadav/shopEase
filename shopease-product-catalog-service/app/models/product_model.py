"""Table products.

Money is DECIMAL(10, 2), read and written as Python Decimal, never float.
stock_quantity is the current stock. It changes only through inventory transactions
(app/services/inventory_service.py), so every change has a history row.
Products are deactivated (is_active = False), not deleted, so their history stays valid.
"""

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, WriteOnlyMapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.category_model import Category
    from app.models.inventory_model import InventoryTransaction

# DECIMAL(10, 2): up to 99,999,999.99.
MONEY = Numeric(10, 2, asdecimal=True)
PRODUCT_NAME_LENGTH = 200
SKU_LENGTH = 64
BRAND_LENGTH = 100
IMAGE_URL_LENGTH = 500


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    # CHECK constraints are enforced by MySQL 8.0.16 and later (and by SQLite in tests).
    __table_args__ = (
        CheckConstraint("price >= 0", name="price_non_negative"),
        # A discount must be a real reduction: at least 0 and below the normal price.
        CheckConstraint(
            "discount_price IS NULL OR (discount_price >= 0 AND discount_price < price)",
            name="discount_price_valid",
        ),
        CheckConstraint("stock_quantity >= 0", name="stock_quantity_non_negative"),
        CheckConstraint("TRIM(name) <> ''", name="name_not_blank"),
        CheckConstraint("TRIM(sku) <> ''", name="sku_not_blank"),
        # For sorting the product list by newest first (sort_by=created_at).
        Index("ix_products_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(PRODUCT_NAME_LENGTH), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Unique constraint uq_products_sku; MySQL backs it with a unique index used for SKU lookups.
    # Stored upper-case by the schemas, so "abc-1" and "ABC-1" are the same SKU.
    sku: Mapped[str] = mapped_column(String(SKU_LENGTH), nullable=False, unique=True)
    # Indexed for the price range filter and sort_by=price.
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False, index=True)
    discount_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # active_history: the old value is loaded before a change, so app.models.stock_guard can check
    # that the change matches its inventory transactions.
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0",
                                                active_history=True)
    image_url: Mapped[str | None] = mapped_column(String(IMAGE_URL_LENGTH), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(BRAND_LENGTH), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    category: Mapped["Category"] = relationship(back_populates="products")
    # Write-only: the history can grow large, so it is never loaded as a whole by accident.
    # Read it with a query (see inventory_service.list_transactions).
    inventory_transactions: WriteOnlyMapped["InventoryTransaction"] = relationship(
        back_populates="product", passive_deletes="all"
    )

    @property
    def in_stock(self) -> bool:
        return self.stock_quantity > 0

    @property
    def effective_price(self) -> Decimal:
        """What a customer pays: the discount price when there is one."""
        return self.discount_price if self.discount_price is not None else self.price

    def __repr__(self) -> str:
        return f"Product(id={self.id!r}, sku={self.sku!r})"
