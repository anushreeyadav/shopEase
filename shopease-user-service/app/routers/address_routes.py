"""HTTP layer for user addresses: request handling only, no business logic.

Every route depends on get_current_authenticated_user, and the address owner is always that
verified caller. The only ID a client sends is address_id in the path, and the service only
finds it among the caller's own addresses. Someone else's address gives 404, the same as an
address that does not exist, so its existence is not disclosed.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.core.security import MAX_DB_INT, AuthenticatedUser, get_current_authenticated_user
from app.database.connection import get_db
from app.routers.user_routes import AUTH_ERRORS, ERROR_RESPONSES as PROFILE_ERROR_RESPONSES, INVALID
from app.schemas.address_schema import AddressCreate, AddressReplace, AddressResponse
from app.schemas.user_schema import ErrorResponse, MessageResponse
from app.services import address_service

router = APIRouter(prefix="/users/addresses", tags=["Addresses"])

AddressId = Annotated[int, Path(ge=1, le=MAX_DB_INT, description="ID of one of the caller's addresses")]

NO_PROFILE = {404: {"model": ErrorResponse, "description": "The caller has no profile yet"}}
NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such address among the caller's addresses, or no profile"}}

ERROR_RESPONSES = {
    **PROFILE_ERROR_RESPONSES,
    address_service.AddressNotFoundError: (status.HTTP_404_NOT_FOUND, "Address not found"),
    address_service.DefaultAddressNotFoundError: (status.HTTP_404_NOT_FOUND, "Default address not found"),
}
ADDRESS_ERRORS = tuple(ERROR_RESPONSES)


def _http_error(exc: Exception) -> HTTPException:
    status_code, detail = ERROR_RESPONSES[type(exc)]
    return HTTPException(status_code=status_code, detail=detail)


@router.post(
    "",
    response_model=AddressResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add an address",
    description=(
        "The caller's first address always becomes the default. With is_default true, the new "
        "address replaces the old default."
    ),
    responses={**AUTH_ERRORS, **NO_PROFILE, **INVALID},
)
def create_address(
    request: AddressCreate,
    user: AuthenticatedUser = Depends(get_current_authenticated_user),
    db: Session = Depends(get_db),
):
    try:
        return address_service.create_address(db, user.auth_user_id, request)
    except ADDRESS_ERRORS as exc:
        raise _http_error(exc) from exc


@router.get(
    "",
    response_model=list[AddressResponse],
    summary="List the caller's addresses",
    description="The default address comes first, then the others from oldest to newest.",
    responses={**AUTH_ERRORS, **NO_PROFILE},
)
def list_addresses(
    user: AuthenticatedUser = Depends(get_current_authenticated_user),
    db: Session = Depends(get_db),
):
    try:
        return address_service.list_addresses(db, user.auth_user_id)
    except ADDRESS_ERRORS as exc:
        raise _http_error(exc) from exc


# Declared before /{address_id}, which would otherwise match "default" and reject it with 422.
@router.get(
    "/default",
    response_model=AddressResponse,
    summary="Get the caller's default delivery address",
    responses={**AUTH_ERRORS, 404: {"model": ErrorResponse, "description": "No default address (no addresses), or no profile"}},
)
def read_default_address(
    user: AuthenticatedUser = Depends(get_current_authenticated_user),
    db: Session = Depends(get_db),
):
    try:
        return address_service.get_default_address(db, user.auth_user_id)
    except ADDRESS_ERRORS as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{address_id}",
    response_model=AddressResponse,
    summary="Get one of the caller's addresses",
    responses={**AUTH_ERRORS, **NOT_FOUND, **INVALID},
)
def read_address(
    address_id: AddressId,
    user: AuthenticatedUser = Depends(get_current_authenticated_user),
    db: Session = Depends(get_db),
):
    try:
        return address_service.get_address(db, user.auth_user_id, address_id)
    except ADDRESS_ERRORS as exc:
        raise _http_error(exc) from exc


@router.put(
    "/{address_id}",
    response_model=AddressResponse,
    summary="Replace one of the caller's addresses",
    description=(
        "Full update: every field is replaced. An omitted address_line_2 is set to null and an "
        "omitted address_type to HOME. is_default is not accepted; use PATCH .../default."
    ),
    responses={**AUTH_ERRORS, **NOT_FOUND, **INVALID},
)
def replace_address(
    address_id: AddressId,
    request: AddressReplace,
    user: AuthenticatedUser = Depends(get_current_authenticated_user),
    db: Session = Depends(get_db),
):
    try:
        return address_service.replace_address(db, user.auth_user_id, address_id, request)
    except ADDRESS_ERRORS as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{address_id}",
    response_model=MessageResponse,
    summary="Delete one of the caller's addresses",
    description="Deleting the default address makes the oldest remaining address the default.",
    responses={**AUTH_ERRORS, **NOT_FOUND, **INVALID},
)
def delete_address(
    address_id: AddressId,
    user: AuthenticatedUser = Depends(get_current_authenticated_user),
    db: Session = Depends(get_db),
):
    try:
        address_service.delete_address(db, user.auth_user_id, address_id)
    except ADDRESS_ERRORS as exc:
        raise _http_error(exc) from exc
    return MessageResponse(message="Address deleted")


@router.patch(
    "/{address_id}/default",
    response_model=AddressResponse,
    summary="Make an address the default delivery address",
    description="Clears the previous default in the same transaction. Takes no request body.",
    responses={**AUTH_ERRORS, **NOT_FOUND, **INVALID},
)
def set_default_address(
    address_id: AddressId,
    user: AuthenticatedUser = Depends(get_current_authenticated_user),
    db: Session = Depends(get_db),
):
    try:
        return address_service.set_default_address(db, user.auth_user_id, address_id)
    except ADDRESS_ERRORS as exc:
        raise _http_error(exc) from exc
