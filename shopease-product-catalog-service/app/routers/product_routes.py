"""HTTP layer for products: request handling only, no business logic.

Browsing is public: anonymous visitors and customers (role USER) see only active products in
active categories. Writes, and seeing inactive products, need the ADMIN role.

The collection is served at both /api/products/ (documented) and /api/products, so neither form
is answered with a redirect.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.core.security import (
    MAX_DB_INT,
    AuthenticatedUser,
    ensure_admin_for_inactive,
    get_optional_user,
    require_admin,
)
from app.database.connection import get_db
from app.routers.responses import ADMIN_ERRORS, BAD_BODY, NOT_FOUND, OPTIONAL_AUTH_ERRORS
from app.schemas.common_schema import ErrorResponse, MessageResponse, ValidationErrorResponse
from app.schemas.product_schema import (
    ProductCreate,
    ProductListQuery,
    ProductListResponse,
    ProductReplace,
    ProductResponse,
    ProductUpdate,
)
from app.services import product_service

router = APIRouter(prefix="/products", tags=["Products"])

ProductIdPath = Annotated[int, Path(ge=1, le=MAX_DB_INT, description="Product ID (a positive whole number)")]
IncludeInactive = Annotated[bool, Query(description="Also return inactive products and products in inactive "
                                                    "categories. Needs an ADMIN token.")]

DUPLICATE_SKU = {409: {"model": ErrorResponse, "description": "Another product already has this SKU "
                                                             "(letter case is ignored)"}}
INVALID_QUERY = {422: {"model": ValidationErrorResponse, "description": (
    "Invalid or unknown query parameter: for example page 0, page_size above 100, a sort_by column that is "
    "not allowed, a negative price, or max_price below min_price")}}
INVALID_PRODUCT = {422: {"model": ValidationErrorResponse, "description": (
    "Invalid fields: for example a missing required field, negative price, discount not below price, "
    "unknown or inactive category, or a read-only field such as stock_quantity")}}


@router.get(
    "/",
    response_model=ProductListResponse,
    summary="List, search, filter and sort products",
    description=(
        "Public: no token needed. Customers and visitors get only active products in active "
        "categories, whatever the filters.\n\n"
        "| Parameter | Meaning |\n"
        "|---|---|\n"
        "| `search` | Part of the name or SKU, ignoring case |\n"
        "| `category_id` | Only this category |\n"
        "| `min_price`, `max_price` | Price range, inclusive, on the normal price |\n"
        "| `availability` | `in_stock` (stock above 0) or `out_of_stock` (stock 0) |\n"
        "| `brand` | Exact brand, ignoring case |\n"
        "| `page`, `page_size` | Page from 1; page size 1 to 100, default 20 |\n"
        "| `sort_by`, `sort_order` | `name`, `price` or `created_at`; `asc` or `desc`. Default: name, asc |\n"
        "| `include_inactive` | With an ADMIN token: inactive products too |\n\n"
        "Filters combine with AND. A page past the last one returns no items, with the correct `total`. "
        "Unknown parameters are refused with 422.\n\n"
        "Examples: `?search=mobile`, `?category_id=1`, `?min_price=1000&max_price=5000`, "
        "`?page=1&page_size=10`, `?sort_by=price&sort_order=asc`, "
        "`?search=phone&availability=in_stock&sort_by=price&sort_order=desc`"
    ),
    responses={**OPTIONAL_AUTH_ERRORS, **INVALID_QUERY},
)
@router.get("", response_model=ProductListResponse, include_in_schema=False)
def list_products(
    query: Annotated[ProductListQuery, Query()],
    user: AuthenticatedUser | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    ensure_admin_for_inactive(query.include_inactive, user)
    items, total = product_service.list_products(db, query)
    return ProductListResponse.build([ProductResponse.model_validate(item) for item in items], total, query)


@router.get(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Get a product",
    description=(
        "Public: no token needed. A missing product, an inactive one, or one in an inactive category "
        "returns 404, unless `include_inactive=true` is sent with an ADMIN token."
    ),
    responses={**OPTIONAL_AUTH_ERRORS, **NOT_FOUND},
)
def read_product(
    product_id: ProductIdPath,
    include_inactive: IncludeInactive = False,
    user: AuthenticatedUser | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    ensure_admin_for_inactive(include_inactive, user)
    return product_service.get_product(db, product_id, include_inactive=include_inactive)


@router.post(
    "/",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product (ADMIN)",
    description=(
        "Required: `category_id` (an existing, active category), `name`, `sku` (unique, ignoring case) "
        "and `price`. `discount_price` must be lower than `price`. Prices are decimals with up to two "
        "places, sent preferably as strings (\"19.99\").\n\n"
        "`initial_stock` above 0 is recorded as the product's first IN inventory transaction. "
        "`stock_quantity` cannot be set directly."
    ),
    responses={**BAD_BODY, **ADMIN_ERRORS, **DUPLICATE_SKU, **INVALID_PRODUCT},
)
@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_product(
    request: ProductCreate,
    _admin: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return product_service.create_product(db, request)


@router.put(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Replace a product (ADMIN)",
    description=(
        "Sets every editable field; all are required. `description`, `discount_price`, `image_url` "
        "and `brand` may be null, which clears them. `is_active: false` deactivates the product, "
        "`true` reactivates it. Stock is not changed: use /api/inventory.\n\n"
        "A new `category_id` must refer to an active category."
    ),
    responses={**BAD_BODY, **ADMIN_ERRORS, **NOT_FOUND, **DUPLICATE_SKU, **INVALID_PRODUCT},
)
def replace_product(
    product_id: ProductIdPath,
    request: ProductReplace,
    _admin: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return product_service.replace_product(db, product_id, request)


@router.patch(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Update some fields of a product (ADMIN)",
    description=(
        "Only the fields sent are changed, for example `{\"price\": \"17.99\"}` or "
        "`{\"is_active\": false}`. A `discount_price` or `price` sent alone is checked against the "
        "stored value of the other. `stock_quantity` is not accepted: stock changes only through "
        "/api/inventory, so that every change is recorded."
    ),
    responses={**BAD_BODY, **ADMIN_ERRORS, **NOT_FOUND, **DUPLICATE_SKU, **INVALID_PRODUCT},
)
def update_product(
    product_id: ProductIdPath,
    request: ProductUpdate,
    _admin: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return product_service.update_product(db, product_id, request.model_dump(exclude_unset=True))


@router.delete(
    "/{product_id}",
    response_model=MessageResponse,
    summary="Delete (deactivate) a product (ADMIN)",
    description=(
        "Soft delete: sets `is_active` to false and keeps the record, so its inventory history and "
        "orders in other ShopEase services still refer to a valid product. The product disappears "
        "from public listings at once. Reactivate it with PUT or PATCH and `is_active: true`."
    ),
    responses={**ADMIN_ERRORS, **NOT_FOUND},
)
def deactivate_product(
    product_id: ProductIdPath,
    _admin: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    product_service.deactivate_product(db, product_id)
    return MessageResponse(message="Product deactivated")
