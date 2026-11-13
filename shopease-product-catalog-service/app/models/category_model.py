"""Table categories: product categories.

A category that still has products cannot be deleted: products.category_id uses ON DELETE RESTRICT.
"""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.product_model import Product

CATEGORY_NAME_LENGTH = 100


class Category(TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (CheckConstraint("TRIM(name) <> ''", name="name_not_blank"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Unique constraint uq_categories_name. MySQL's default collation (utf8mb4_0900_ai_ci)
    # also makes it ignore letter case, so "Shoes" and "shoes" cannot both exist.
    name: Mapped[str] = mapped_column(String(CATEGORY_NAME_LENGTH), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        # "1", not true(): MySQL reports a BOOLEAN default as 1, and this keeps autogenerate quiet.
        Boolean, nullable=False, default=True, server_default="1"
    )

    # passive_deletes="all": the ORM never touches products when a category is deleted, so the
    # database's ON DELETE RESTRICT refuses the delete instead of products being orphaned.
    products: Mapped[list["Product"]] = relationship(back_populates="category", passive_deletes="all")

    def __repr__(self) -> str:
        return f"Category(id={self.id!r}, name={self.name!r})"
