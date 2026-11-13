"""HTTP layer for categories: request handling only, no business logic.

Reading active categories is public: anonymous visitors and customers (role USER) see only
active ones. Writes, and seeing inactive categories, need the ADMIN role.
Service errors (not found, conflict) are turned into responses in app/main.py.

The collection is served at both /api/categories/ (documented) and /api/categories, so neither
form is answered with a redirect.
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
from app.routers.responses import ADMIN_ERRORS, BAD_BODY, INVALID, NOT_FOUND, OPTIONAL_AUTH_ERRORS
from app.schemas.category_schema import CategoryCreate, CategoryReplace, CategoryResponse, CategoryUpdate
from app.schemas.common_schema import ErrorResponse, MessageResponse
from app.services import category_service

router = APIRouter(prefix="/categories", tags=["Categories"])

CategoryIdPath = Annotated[int, Path(ge=1, le=MAX_DB_INT, description="Category ID (a positive whole number)")]
IncludeInactive = Annotated[bool, Query(description="Also return inactive categories. Needs an ADMIN token.")]

DUPLICATE_NAME = {409: {"model": ErrorResponse, "description": "Another category already has this name "
                                                              "(letter case is ignored)"}}
HAS_PRODUCTS = {409: {"model": ErrorResponse, "description": "The category still contains products"}}


@router.get(
    "/",
    response_model=list[CategoryResponse],
    summary="List categories",
    description=(
        "Public: no token needed. Returns active categories sorted by name.\n\n"
        "With `include_inactive=true` and an ADMIN token, inactive categories are included."
    ),
    responses=OPTIONAL_AUTH_ERRORS,
)
@router.get("", response_model=list[CategoryResponse], include_in_schema=False)
def list_categories(
    include_inactive: IncludeInactive = False,
    user: AuthenticatedUser | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    ensure_admin_for_inactive(include_inactive, user)
    return category_service.list_categories(db, include_inactive=include_inactive)


@router.get(
    "/{category_id}",
    response_model=CategoryResponse,
    summary="Get a category",
    description=(
        "Public: no token needed. An inactive category returns 404, unless `include_inactive=true` "
        "is sent with an ADMIN token."
    ),
    responses={**OPTIONAL_AUTH_ERRORS, **NOT_FOUND},
)
def read_category(
    category_id: CategoryIdPath,
    include_inactive: IncludeInactive = False,
    user: AuthenticatedUser | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    ensure_admin_for_inactive(include_inactive, user)
    return category_service.get_category(db, category_id, include_inactive=include_inactive)


@router.post(
    "/",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a category (ADMIN)",
    description=(
        "Creates an active category. `name` is required and must be unique, ignoring letter case. "
        "Surrounding spaces are removed and inner runs of spaces become one."
    ),
    responses={**BAD_BODY, **ADMIN_ERRORS, **DUPLICATE_NAME, **INVALID},
)
@router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_category(
    request: CategoryCreate,
    _admin: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return category_service.create_category(db, request)


@router.put(
    "/{category_id}",
    response_model=CategoryResponse,
    summary="Replace a category (ADMIN)",
    description=(
        "Sets every field: `name`, `description` (null clears it) and `is_active` are all required. "
        "`is_active: false` deactivates the category, which hides it and its products from public "
        "listings; `true` activates it again. Works on inactive categories too."
    ),
    responses={**BAD_BODY, **ADMIN_ERRORS, **NOT_FOUND, **DUPLICATE_NAME, **INVALID},
)
def replace_category(
    category_id: CategoryIdPath,
    request: CategoryReplace,
    _admin: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return category_service.replace_category(db, category_id, request)


@router.patch(
    "/{category_id}",
    response_model=CategoryResponse,
    summary="Update some fields of a category (ADMIN)",
    description=(
        "Only the fields sent are changed, for example `{\"is_active\": false}` to deactivate. "
        "Use PUT to send the complete category."
    ),
    responses={**BAD_BODY, **ADMIN_ERRORS, **NOT_FOUND, **DUPLICATE_NAME, **INVALID},
)
def update_category(
    category_id: CategoryIdPath,
    request: CategoryUpdate,
    _admin: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return category_service.update_category(db, category_id, request.model_dump(exclude_unset=True))


@router.delete(
    "/{category_id}",
    response_model=MessageResponse,
    summary="Delete an empty category (ADMIN)",
    description=(
        "Permanently deletes a category that contains no products, active or inactive.\n\n"
        "**Policy:** if it still contains products, the request is refused with 409 and nothing "
        "changes. Products are never moved or deleted automatically. Either deactivate the category "
        "(PUT or PATCH with `is_active: false`), or move its products to another category "
        "(PATCH /api/products/{id} with a new `category_id`) and then delete it."
    ),
    responses={**ADMIN_ERRORS, **NOT_FOUND, **HAS_PRODUCTS},
)
def delete_category(
    category_id: CategoryIdPath,
    _admin: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    category_service.delete_category(db, category_id)
    return MessageResponse(message="Category deleted")
