"""Public /api/products and /api/categories routes (rest_api_notes.md §3.4).

Reads are public (archived products only for admins). Every change to the catalog, prices
or stock requires the admin role, checked here, not only at the gateway.
"""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import func, select

from app import catalog, stock
from app.dependencies import DbSession
from app.models import Inventory, InventoryMovement, ProductStatus
from app.schemas import (
    CategoryCreate,
    CategoryRead,
    CategoryUpdate,
    InventoryAdjust,
    InventoryRead,
    MovementRead,
    Page,
    ProductCreate,
    ProductDetail,
    ProductSort,
    ProductSummary,
    ProductUpdate,
)
from shopease_shared import ShopEaseError
from shopease_shared.security import AdminUser, OptionalUser

router = APIRouter(prefix="/api/products", tags=["products"])
categories_router = APIRouter(prefix="/api/categories", tags=["categories"])

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


def _validation(field: str, issue: str) -> ShopEaseError:
    return ShopEaseError(422, "VALIDATION_ERROR", "Request validation failed.", [{"field": field, "issue": issue}])


# --- Products --------------------------------------------------------------------------


@router.get("", response_model=Page[ProductSummary], summary="List, filter and search products")
def list_products(
    session: DbSession,
    user: OptionalUser,
    q: Annotated[str | None, Query(max_length=100, description="Search name, SKU and description")] = None,
    category_id: UUID | None = None,
    min_price: Annotated[Decimal | None, Query(ge=0)] = None,
    max_price: Annotated[Decimal | None, Query(ge=0)] = None,
    in_stock: bool | None = None,
    status: Annotated[ProductStatus | None, Query(description="Admins only")] = None,
    sort: ProductSort = "name",
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[ProductSummary]:
    if min_price is not None and max_price is not None and min_price > max_price:
        raise _validation("query.min_price", "must not be greater than max_price")
    is_admin = user is not None and user.is_admin
    if status is not None and not is_admin:
        raise ShopEaseError(403, "FORBIDDEN", "Filtering by status requires the admin role.")
    items, total = catalog.list_products(
        session,
        q=q,
        category_id=category_id,
        min_price=min_price,
        max_price=max_price,
        in_stock=in_stock,
        status=status,
        include_archived=is_admin,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return Page[ProductSummary](items=items, total=total, limit=limit, offset=offset)


@router.get("/{product_id}", response_model=ProductDetail, summary="Get one product")
def get_product(product_id: UUID, session: DbSession, user: OptionalUser) -> ProductDetail:
    include_archived = user is not None and user.is_admin
    return catalog.product_detail(session, catalog.get_product(session, product_id, include_archived))


@router.post("", status_code=201, response_model=ProductDetail, summary="Create a product (admin)")
def create_product(body: ProductCreate, admin: AdminUser, session: DbSession, response: Response) -> ProductDetail:
    product = catalog.create_product(session, body.model_dump(), actor=str(admin.user_id))
    response.headers["Location"] = f"/api/products/{product.id}"
    return catalog.product_detail(session, product)


@router.patch("/{product_id}", response_model=ProductDetail, summary="Update a product (admin)")
def update_product(product_id: UUID, body: ProductUpdate, admin: AdminUser, session: DbSession) -> ProductDetail:
    product = catalog.update_product(session, product_id, body.model_dump(exclude_unset=True))
    return catalog.product_detail(session, product)


@router.delete("/{product_id}", status_code=204, summary="Deactivate (archive) a product (admin)")
def archive_product(product_id: UUID, admin: AdminUser, session: DbSession) -> None:
    catalog.archive_product(session, product_id)


@router.get("/{product_id}/inventory", response_model=InventoryRead, summary="Stock levels (admin)")
def get_inventory(product_id: UUID, admin: AdminUser, session: DbSession) -> InventoryRead:
    catalog.get_product(session, product_id, include_archived=True)
    return InventoryRead.model_validate(session.get(Inventory, product_id))


@router.patch("/{product_id}/inventory", response_model=InventoryRead, summary="Restock or adjust stock (admin)")
def adjust_inventory(product_id: UUID, body: InventoryAdjust, admin: AdminUser, session: DbSession) -> InventoryRead:
    inventory = stock.adjust_stock(
        session, product_id, body.quantity_change, body.reason, actor=str(admin.user_id), note=body.note
    )
    return InventoryRead.model_validate(inventory)


@router.get(
    "/{product_id}/inventory/movements",
    response_model=Page[MovementRead],
    summary="Stock audit trail, newest first (admin)",
)
def list_movements(
    product_id: UUID, admin: AdminUser, session: DbSession, limit: Limit = 20, offset: Offset = 0
) -> Page[MovementRead]:
    catalog.get_product(session, product_id, include_archived=True)
    owned = InventoryMovement.product_id == product_id
    total = session.scalar(select(func.count()).select_from(InventoryMovement).where(owned))
    rows = session.scalars(
        select(InventoryMovement)
        .where(owned)
        .order_by(InventoryMovement.created_at.desc(), InventoryMovement.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return Page[MovementRead](
        items=[MovementRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


# --- Categories --------------------------------------------------------------------------


@categories_router.get("", response_model=Page[CategoryRead], summary="List categories")
def list_categories(
    session: DbSession, parent_id: UUID | None = None, limit: Limit = 20, offset: Offset = 0
) -> Page[CategoryRead]:
    items, total = catalog.list_categories(session, parent_id, limit, offset)
    return Page[CategoryRead](
        items=[CategoryRead.model_validate(c) for c in items], total=total, limit=limit, offset=offset
    )


@categories_router.get("/{category_id}", response_model=CategoryRead, summary="Get one category")
def get_category(category_id: UUID, session: DbSession) -> CategoryRead:
    return CategoryRead.model_validate(catalog.get_category(session, category_id))


@categories_router.post("", status_code=201, response_model=CategoryRead, summary="Create a category (admin)")
def create_category(body: CategoryCreate, admin: AdminUser, session: DbSession, response: Response) -> CategoryRead:
    category = catalog.create_category(session, body.name, body.parent_id)
    response.headers["Location"] = f"/api/categories/{category.id}"
    return CategoryRead.model_validate(category)


@categories_router.patch("/{category_id}", response_model=CategoryRead, summary="Rename or move a category (admin)")
def update_category(category_id: UUID, body: CategoryUpdate, admin: AdminUser, session: DbSession) -> CategoryRead:
    return CategoryRead.model_validate(
        catalog.update_category(session, category_id, body.model_dump(exclude_unset=True))
    )


@categories_router.delete("/{category_id}", status_code=204, summary="Delete an unused category (admin)")
def delete_category(category_id: UUID, admin: AdminUser, session: DbSession) -> None:
    catalog.delete_category(session, category_id)
