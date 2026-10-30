"""Catalog rules: products and categories. Stock changes live in app/stock.py."""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import category_not_found, product_not_found
from app.models import Category, Inventory, MovementReason, Product, ProductStatus
from app.schemas import CategoryRef, ProductDetail, ProductSummary
from app.stock import record_movement
from shopease_shared import ShopEaseError


def _available():
    return Inventory.quantity_on_hand - Inventory.quantity_reserved


# --- Categories ------------------------------------------------------------------------


def list_categories(session: Session, parent_id: uuid.UUID | None, limit: int, offset: int):
    query = select(Category)
    if parent_id is not None:
        query = query.where(Category.parent_id == parent_id)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    items = session.scalars(query.order_by(Category.name, Category.id).limit(limit).offset(offset)).all()
    return list(items), total


def get_category(session: Session, category_id: uuid.UUID) -> Category:
    category = session.get(Category, category_id)
    if category is None:
        raise category_not_found(category_id)
    return category


def _require_category(session: Session, category_id: uuid.UUID | None, field: str) -> None:
    """A reference in a request body to a category that doesn't exist is a validation error."""
    if category_id is not None and session.get(Category, category_id) is None:
        raise ShopEaseError(
            422,
            "CATEGORY_NOT_FOUND",
            "The referenced category does not exist.",
            details=[{"field": f"body.{field}", "issue": "unknown category"}],
        )


def _commit_unique(session: Session, code: str, message: str) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ShopEaseError(409, code, message) from exc


def create_category(session: Session, name: str, parent_id: uuid.UUID | None) -> Category:
    _require_category(session, parent_id, "parent_id")
    category = Category(name=name, parent_id=parent_id)
    session.add(category)
    _commit_unique(session, "DUPLICATE_CATEGORY", "A category with this name already exists.")
    return category


def update_category(session: Session, category_id: uuid.UUID, changes: dict[str, Any]) -> Category:
    category = get_category(session, category_id)
    if "parent_id" in changes and changes["parent_id"] is not None:
        parent_id = changes["parent_id"]
        _require_category(session, parent_id, "parent_id")
        # Walk up from the new parent: reaching this category would create a cycle.
        node: uuid.UUID | None = parent_id
        while node is not None:
            if node == category.id:
                raise ShopEaseError(
                    422,
                    "INVALID_CATEGORY_PARENT",
                    "A category cannot be its own parent or descendant.",
                    details=[{"field": "body.parent_id", "issue": "would create a cycle"}],
                )
            node = session.scalar(select(Category.parent_id).where(Category.id == node))
    for field, value in changes.items():
        setattr(category, field, value)
    _commit_unique(session, "DUPLICATE_CATEGORY", "A category with this name already exists.")
    return category


def delete_category(session: Session, category_id: uuid.UUID) -> None:
    category = get_category(session, category_id)
    in_use = session.scalar(select(func.count()).select_from(Product).where(Product.category_id == category_id))
    children = session.scalar(select(func.count()).select_from(Category).where(Category.parent_id == category_id))
    if in_use or children:
        raise ShopEaseError(
            409, "CATEGORY_IN_USE", "The category still has products or subcategories; move them first."
        )
    session.delete(category)
    session.commit()


# --- Products --------------------------------------------------------------------------


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _product_query(include_archived: bool) -> Select:
    query = select(Product, _available().label("available")).join(Inventory, Inventory.product_id == Product.id)
    if not include_archived:
        query = query.where(Product.status == ProductStatus.ACTIVE)
    return query


_SORTS = {
    "price": (Product.price, Product.id),
    "-price": (Product.price.desc(), Product.id),
    "name": (Product.name, Product.id),
    "-name": (Product.name.desc(), Product.id),
    "created_at": (Product.created_at, Product.id),
    "-created_at": (Product.created_at.desc(), Product.id),
}


def list_products(
    session: Session,
    *,
    q: str | None,
    category_id: uuid.UUID | None,
    min_price: Decimal | None,
    max_price: Decimal | None,
    in_stock: bool | None,
    status: ProductStatus | None,
    include_archived: bool,
    sort: str,
    limit: int,
    offset: int,
) -> tuple[list[ProductSummary], int]:
    query = _product_query(include_archived)
    if status is not None:
        query = query.where(Product.status == status)
    if q:
        pattern = f"%{_escape_like(q.strip())}%"
        query = query.where(
            or_(
                Product.name.like(pattern, escape="\\"),
                Product.sku.like(pattern, escape="\\"),
                Product.description.like(pattern, escape="\\"),
            )
        )
    if category_id is not None:
        query = query.where(Product.category_id == category_id)
    if min_price is not None:
        query = query.where(Product.price >= min_price)
    if max_price is not None:
        query = query.where(Product.price <= max_price)
    if in_stock is True:
        query = query.where(_available() > 0)
    elif in_stock is False:
        query = query.where(_available() <= 0)

    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = session.execute(query.order_by(*_SORTS[sort]).limit(limit).offset(offset)).all()
    items = [
        ProductSummary(
            product_id=p.id,
            sku=p.sku,
            name=p.name,
            price=p.price,
            currency=p.currency,
            category_id=p.category_id,
            status=p.status,
            in_stock=available > 0,
        )
        for p, available in rows
    ]
    return items, total


def get_product(session: Session, product_id: uuid.UUID, include_archived: bool = False) -> Product:
    product = session.get(Product, product_id)
    if product is None or (product.status is ProductStatus.ARCHIVED and not include_archived):
        raise product_not_found(product_id)
    return product


def product_detail(session: Session, product: Product) -> ProductDetail:
    inventory = session.get(Inventory, product.id)
    available = inventory.quantity_on_hand - inventory.quantity_reserved if inventory else 0
    return ProductDetail(
        product_id=product.id,
        sku=product.sku,
        name=product.name,
        description=product.description,
        price=product.price,
        currency=product.currency,
        category=CategoryRef(category_id=product.category.id, name=product.category.name)
        if product.category
        else None,
        available_quantity=available,
        status=product.status,
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


def create_product(session: Session, fields: dict[str, Any], actor: str) -> Product:
    initial_stock = fields.pop("initial_stock")
    _require_category(session, fields.get("category_id"), "category_id")
    product = Product(id=uuid.uuid4(), **fields)
    session.add(product)
    inventory = Inventory(product_id=product.id, quantity_on_hand=initial_stock, quantity_reserved=0)
    session.add(inventory)
    if initial_stock:
        record_movement(session, inventory, MovementReason.RESTOCK, initial_stock, 0, actor, note="initial stock")
    _commit_unique(session, "DUPLICATE_SKU", f"A product with SKU {fields['sku']} already exists.")
    return product


def update_product(session: Session, product_id: uuid.UUID, changes: dict[str, Any]) -> Product:
    product = get_product(session, product_id, include_archived=True)
    if "category_id" in changes:
        _require_category(session, changes["category_id"], "category_id")
    for field, value in changes.items():
        setattr(product, field, value)
    session.commit()
    return product


def archive_product(session: Session, product_id: uuid.UUID) -> None:
    """Deactivate: hidden from customers and not orderable. Orders keep their snapshots."""
    product = get_product(session, product_id, include_archived=True)
    product.status = ProductStatus.ARCHIVED
    session.commit()
