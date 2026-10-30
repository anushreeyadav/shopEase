"""product_db catalog tables: categories and products."""

import enum
import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey, str_enum


class ProductStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"  # products are archived, never deleted: old orders still refer to them


class Category(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id"), index=True)

    parent: Mapped["Category | None"] = relationship(remote_side="Category.id")


class Product(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0", name="price_non_negative"),
        Index("ix_products_status_category_id", "status", "category_id"),
    )

    sku: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id"), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")  # ISO 4217
    status: Mapped[ProductStatus] = mapped_column(
        str_enum(ProductStatus, "status"), default=ProductStatus.ACTIVE
    )

    category: Mapped[Category | None] = relationship()
