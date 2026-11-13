"""Table inventory_transactions: the stock history of every product.

Each row records one stock movement:
    IN   stock received:  updated_stock = previous_stock + quantity
    OUT  stock removed:   updated_stock = previous_stock - quantity
CHECK constraints enforce that arithmetic, a positive quantity and non-negative stock, so a
history row can never disagree with itself. Rows are only ever inserted, never changed.
"""

import enum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, CreatedAtMixin

if TYPE_CHECKING:
    from app.models.product_model import Product

REMARKS_LENGTH = 255


class TransactionType(str, enum.Enum):
    IN = "IN"
    OUT = "OUT"


class InventoryTransaction(CreatedAtMixin, Base):
    __tablename__ = "inventory_transactions"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("previous_stock >= 0", name="previous_stock_non_negative"),
        CheckConstraint("updated_stock >= 0", name="updated_stock_non_negative"),
        CheckConstraint(
            "(transaction_type = 'IN' AND updated_stock = previous_stock + quantity)"
            " OR (transaction_type = 'OUT' AND updated_stock = previous_stock - quantity)",
            name="stock_arithmetic",
        ),
        # A product's history, newest first: WHERE product_id = ? ORDER BY created_at DESC.
        # It also serves as the index MySQL requires for the product_id foreign key.
        Index(None, "product_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        # RESTRICT: a product with history cannot be deleted, so the history is never lost.
        Integer, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    # VARCHAR + CHECK constraint (not a MySQL ENUM), so new types need no column rebuild.
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, name="transaction_type", native_enum=False, create_constraint=True,
             length=3, validate_strings=True),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_stock: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_stock: Mapped[int] = mapped_column(Integer, nullable=False)
    remarks: Mapped[str | None] = mapped_column(String(REMARKS_LENGTH), nullable=True)

    product: Mapped["Product"] = relationship(back_populates="inventory_transactions")

    def __repr__(self) -> str:
        return (f"InventoryTransaction(id={self.id!r}, product_id={self.product_id!r}, "
                f"type={self.transaction_type!r}, quantity={self.quantity!r})")
