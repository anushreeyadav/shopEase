"""Business logic for categories.

Names are unique regardless of letter case. Every write is one database transaction: it is
committed at the end, or rolled back if anything fails.

Deletion policy: a category can be deleted only when no product (active or inactive) belongs to
it. Otherwise the request is refused with 409 and nothing changes. To retire such a category,
either deactivate it (is_active false), which hides it and its products from public listings, or
move its products to another category first (PATCH /api/products/{id} with a new category_id)
and then delete it. Products are never moved or deleted automatically.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.connection import is_unique_violation
from app.models.category_model import Category
from app.models.product_model import Product
from app.schemas.category_schema import CategoryCreate, CategoryReplace
from app.services.errors import ConflictError, NotFoundError

_EDITABLE_FIELDS = ("name", "description", "is_active")
_DUPLICATE_NAME = "A category with this name already exists"
_CONFLICT = "The category could not be saved because it conflicts with existing data"


def _not_found() -> NotFoundError:
    return NotFoundError("Category not found")


def _has_products(count: int) -> ConflictError:
    noun, pronoun = ("product", "it") if count == 1 else ("products", "them")
    return ConflictError(
        f"Category still contains {count} {noun} (active or inactive). Move {pronoun} to another "
        "category, or deactivate the category instead of deleting it"
    )


def _find(db: Session, category_id: int, *, for_update: bool = False) -> Category | None:
    statement = select(Category).where(Category.id == category_id)
    if for_update:
        statement = statement.with_for_update()
    return db.scalars(statement).one_or_none()


def _product_count(db: Session, category_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Product).where(Product.category_id == category_id)) or 0


def list_categories(db: Session, *, include_inactive: bool = False) -> list[Category]:
    statement = select(Category).order_by(Category.name, Category.id)
    if not include_inactive:
        statement = statement.where(Category.is_active.is_(True))
    return list(db.scalars(statement))


def get_category(db: Session, category_id: int, *, include_inactive: bool = False) -> Category:
    category = _find(db, category_id)
    if category is None or (not category.is_active and not include_inactive):
        raise _not_found()
    return category


def _check_unique_name(db: Session, name: str, *, exclude_id: int | None = None) -> None:
    # lower() on both sides: MySQL's collation already ignores case, SQLite's does not.
    statement = select(Category.id).where(func.lower(Category.name) == name.lower())
    if exclude_id is not None:
        statement = statement.where(Category.id != exclude_id)
    if db.scalars(statement).first() is not None:
        raise ConflictError(_DUPLICATE_NAME)


def _commit(db: Session) -> None:
    """Commit, or roll back and explain why the database refused the write."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # A unique violation here means a concurrent request took the name between the check and
        # the write, or MySQL's collation treats two names as equal (for example "Café" and "Cafe").
        raise ConflictError(_DUPLICATE_NAME if is_unique_violation(exc) else _CONFLICT) from exc


def create_category(db: Session, data: CategoryCreate) -> Category:
    _check_unique_name(db, data.name)
    category = Category(name=data.name, description=data.description)
    db.add(category)
    _commit(db)
    return category


def update_category(db: Session, category_id: int, changes: dict[str, Any]) -> Category:
    """Change the given fields (PATCH)."""
    category = _find(db, category_id, for_update=True)
    if category is None:
        raise _not_found()
    unknown = set(changes) - set(_EDITABLE_FIELDS)
    if unknown:  # schemas already forbid this; defence in depth
        raise ValueError(f"cannot update {sorted(unknown)}")
    if "name" in changes:
        _check_unique_name(db, changes["name"], exclude_id=category_id)

    for field, value in changes.items():
        setattr(category, field, value)
    _commit(db)
    return category


def replace_category(db: Session, category_id: int, data: CategoryReplace) -> Category:
    """Set every editable field (PUT)."""
    return update_category(db, category_id, data.model_dump())


def delete_category(db: Session, category_id: int) -> None:
    # The row lock makes a concurrent product insert into this category wait until we finish.
    category = _find(db, category_id, for_update=True)
    if category is None:
        raise _not_found()
    count = _product_count(db, category_id)
    if count:
        raise _has_products(count)
    db.delete(category)
    try:
        db.commit()
    except IntegrityError as exc:
        # The foreign key (ON DELETE RESTRICT) refused it: a product was added meanwhile.
        db.rollback()
        raise _has_products(_product_count(db, category_id) or 1) from exc
