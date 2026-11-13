"""Business logic for products.

Visibility: a product is publicly visible only while it and its category are both active.

Deletion: DELETE deactivates a product (soft delete) and keeps the row. Its inventory history
references it (foreign key, RESTRICT), and other ShopEase services (orders) refer to product IDs,
so a removed row would break both. Reactivate with PUT or PATCH and is_active true.

Stock is never set here except through an inventory transaction (initial stock included).

Transactions: every write is one database transaction. It is committed at the end, or rolled
back if anything fails, including the initial-stock transaction row of a new product.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.connection import is_unique_violation
from app.models.category_model import Category
from app.models.inventory_model import TransactionType
from app.models.product_model import Product
from app.schemas.product_schema import ProductCreate, ProductListQuery, ProductReplace, SortBy, check_discount
from app.services import inventory_service
from app.services.errors import ConflictError, InvalidFieldError, NotFoundError

_EDITABLE_FIELDS = (
    "category_id", "name", "description", "sku", "price", "discount_price", "image_url", "brand", "is_active",
)
# The only columns a list can be sorted by; ProductListQuery.sort_by accepts only these keys.
SORT_COLUMNS: dict[SortBy, Any] = {
    "name": Product.name,
    "price": Product.price,
    "created_at": Product.created_at,
}
_DUPLICATE_SKU = "A product with this SKU already exists"
_CONFLICT = "The product could not be saved because it conflicts with existing data"


def _not_found() -> NotFoundError:
    return NotFoundError("Product not found")


def _visible(statement: Select) -> Select:
    """Restrict a query on Product to what the public may see."""
    return statement.join(Product.category).where(Product.is_active.is_(True), Category.is_active.is_(True))


def _list_filters(query: ProductListQuery) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = []
    if query.search:
        # autoescape: % and _ in the search text are matched literally, not as wildcards.
        term = query.search.lower()
        filters.append(
            func.lower(Product.name).contains(term, autoescape=True)
            | func.lower(Product.sku).contains(term, autoescape=True)
        )
    if query.category_id is not None:
        filters.append(Product.category_id == query.category_id)
    if query.min_price is not None:
        filters.append(Product.price >= query.min_price)
    if query.max_price is not None:
        filters.append(Product.price <= query.max_price)
    if query.availability == "in_stock":
        filters.append(Product.stock_quantity > 0)
    elif query.availability == "out_of_stock":
        filters.append(Product.stock_quantity == 0)
    if query.brand:
        filters.append(func.lower(Product.brand) == query.brand.lower())
    return filters


def list_products(db: Session, query: ProductListQuery) -> tuple[list[Product], int]:
    """Return (products on the requested page, number of products matching on all pages).

    Everything happens in the database: the filters are a WHERE clause, the total is a COUNT, and
    only one page of rows is fetched (ORDER BY, LIMIT, OFFSET). Unless include_inactive is set
    (ADMIN only, checked by the router), the visibility rule is part of the same WHERE clause, so
    no filter or search can return a hidden product.
    """
    filters = _list_filters(query)
    count_query = select(func.count(Product.id)).where(*filters)
    item_query = select(Product).where(*filters)
    if not query.include_inactive:
        count_query = _visible(count_query)
        item_query = _visible(item_query)

    total = db.scalar(count_query) or 0
    column = SORT_COLUMNS[query.sort_by]
    # Product.id breaks ties (same name, price or second), so the order is total and pages never
    # overlap or skip a product. It follows the same direction: newest first stays newest first.
    if query.sort_order == "desc":
        order = (column.desc(), Product.id.desc())
    else:
        order = (column.asc(), Product.id.asc())
    items = db.scalars(item_query.order_by(*order).offset(query.offset).limit(query.page_size))
    return list(items), total


def _find(db: Session, product_id: int, *, for_update: bool = False) -> Product | None:
    statement = select(Product).where(Product.id == product_id)
    if for_update:
        statement = statement.with_for_update()
    return db.scalars(statement).one_or_none()


def get_product(db: Session, product_id: int, *, include_inactive: bool = False) -> Product:
    statement = select(Product).where(Product.id == product_id)
    if not include_inactive:
        statement = _visible(statement)
    product = db.scalars(statement).one_or_none()
    if product is None:
        raise _not_found()
    return product


def _check_category(db: Session, category_id: int) -> None:
    """The category must exist and be active.

    FOR SHARE keeps it that way until this transaction ends: a concurrent request cannot delete
    or deactivate it in between (MySQL; SQLite has no row locks and ignores this).
    """
    statement = select(Category).where(Category.id == category_id).with_for_update(read=True)
    category = db.scalars(statement).one_or_none()
    if category is None:
        raise InvalidFieldError("category_id", "category_id does not refer to an existing category")
    if not category.is_active:
        raise InvalidFieldError("category_id", "category_id refers to an inactive category")


def _check_sku(db: Session, sku: str, *, exclude_id: int | None = None) -> None:
    statement = select(Product.id).where(Product.sku == sku)
    if exclude_id is not None:
        statement = statement.where(Product.id != exclude_id)
    if db.scalars(statement).first() is not None:
        raise ConflictError(_DUPLICATE_SKU)


@contextmanager
def _write(db: Session) -> Iterator[None]:
    """One transaction: commit at the end, or roll back and explain why the database refused it.

    Covers flushes inside the block as well as the commit: a new product with initial stock is
    flushed early, and a duplicate SKU can surface there. The message never includes the
    database's own text (constraint names, SQL, values).
    """
    try:
        yield
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # A unique violation means a concurrent request used the same SKU between check and write.
        raise ConflictError(_DUPLICATE_SKU if is_unique_violation(exc) else _CONFLICT) from exc
    except BaseException:
        db.rollback()  # any other failure: nothing from this block is kept
        raise


def create_product(db: Session, data: ProductCreate) -> Product:
    _check_sku(db, data.sku)
    _check_category(db, data.category_id)

    product = Product(**data.model_dump(exclude={"initial_stock"}), stock_quantity=0)
    with _write(db):
        db.add(product)
        if data.initial_stock > 0:
            db.flush()  # assigns product.id for the transaction row
            inventory_service.record_movement(
                db, product, TransactionType.IN, data.initial_stock, inventory_service.INITIAL_STOCK_REMARKS
            )
    return product


def update_product(db: Session, product_id: int, changes: dict[str, Any]) -> Product:
    """Change the given fields (PATCH). Rules involving stored values are checked here."""
    product = _find(db, product_id, for_update=True)
    if product is None:
        raise _not_found()
    unknown = set(changes) - set(_EDITABLE_FIELDS)
    if unknown:  # schemas already forbid this (stock_quantity included); defence in depth
        raise ValueError(f"cannot update {sorted(unknown)}")

    if "sku" in changes and changes["sku"] != product.sku:
        _check_sku(db, changes["sku"], exclude_id=product_id)
    if "category_id" in changes and changes["category_id"] != product.category_id:
        _check_category(db, changes["category_id"])
    if "price" in changes or "discount_price" in changes:
        price = changes.get("price", product.price)
        discount = changes.get("discount_price", product.discount_price)
        try:
            check_discount(price, discount)
        except ValueError as exc:
            raise InvalidFieldError("discount_price", str(exc)) from exc

    with _write(db):
        for field, value in changes.items():
            setattr(product, field, value)
    return product


def replace_product(db: Session, product_id: int, data: ProductReplace) -> Product:
    """Set every editable field (PUT). Stock is not changed."""
    return update_product(db, product_id, data.model_dump())


def deactivate_product(db: Session, product_id: int) -> Product:
    """DELETE: soft delete. Already inactive products stay inactive (repeating it is harmless)."""
    product = _find(db, product_id, for_update=True)
    if product is None:
        raise _not_found()
    with _write(db):
        product.is_active = False
    return product
