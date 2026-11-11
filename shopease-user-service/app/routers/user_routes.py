"""HTTP layer for user profiles: request handling only, no business logic.

Every route depends on get_current_authenticated_user, so the caller's identity always
comes from the Authentication Service's verify-token response, never from the request body,
query, or path. No route takes a profile ID.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, get_current_authenticated_user
from app.database.connection import get_db
from app.schemas.user_schema import (
    ErrorResponse,
    MessageResponse,
    UserProfileCreate,
    UserProfileReplace,
    UserProfileResponse,
    UserProfileUpdate,
    ValidationErrorResponse,
)
from app.services import user_service

router = APIRouter(prefix="/users", tags=["User Profile"])

AUTH_ERRORS = {
    401: {"model": ErrorResponse, "description": "Token missing, invalid, or expired"},
    403: {"model": ErrorResponse, "description": "Inactive Authentication Service user, or profile deactivated"},
    503: {"model": ErrorResponse, "description": "Authentication Service or database unavailable"},
}
NOT_FOUND = {404: {"model": ErrorResponse, "description": "The caller has no profile yet"}}
INVALID = {422: {"model": ValidationErrorResponse, "description": "Invalid request data"}}


ERROR_RESPONSES = {
    user_service.ProfileNotFoundError: (status.HTTP_404_NOT_FOUND, "User profile not found"),
    user_service.ProfileAlreadyExistsError: (status.HTTP_409_CONFLICT, "User profile already exists"),
    user_service.ProfileDeactivatedError: (status.HTTP_403_FORBIDDEN, "User profile is deactivated"),
}
PROFILE_ERRORS = tuple(ERROR_RESPONSES)


def http_error(exc: Exception) -> HTTPException:
    status_code, detail = ERROR_RESPONSES[type(exc)]
    return HTTPException(status_code=status_code, detail=detail)


@router.post(
    "/profile",
    response_model=UserProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create the caller's profile",
    responses={**AUTH_ERRORS, 409: {"model": ErrorResponse, "description": "Profile already exists"}, **INVALID},
)
def create_profile(
    request: UserProfileCreate,
    user: AuthenticatedUser = Depends(get_current_authenticated_user),
    db: Session = Depends(get_db),
):
    try:
        return user_service.create_profile(db, user.auth_user_id, request)
    except PROFILE_ERRORS as exc:
        raise http_error(exc) from exc


@router.get(
    "/profile",
    response_model=UserProfileResponse,
    summary="Get the caller's profile",
    responses={**AUTH_ERRORS, **NOT_FOUND},
)
def read_profile(
    user: AuthenticatedUser = Depends(get_current_authenticated_user),
    db: Session = Depends(get_db),
):
    try:
        return user_service.get_profile(db, user.auth_user_id)
    except PROFILE_ERRORS as exc:
        raise http_error(exc) from exc


@router.put(
    "/profile",
    response_model=UserProfileResponse,
    summary="Replace the caller's profile",
    description="Full update: every field is replaced, and an omitted optional field is set to null.",
    responses={**AUTH_ERRORS, **NOT_FOUND, **INVALID},
)
def replace_profile(
    request: UserProfileReplace,
    user: AuthenticatedUser = Depends(get_current_authenticated_user),
    db: Session = Depends(get_db),
):
    try:
        return user_service.replace_profile(db, user.auth_user_id, request)
    except PROFILE_ERRORS as exc:
        raise http_error(exc) from exc


@router.patch(
    "/profile",
    response_model=UserProfileResponse,
    summary="Update part of the caller's profile",
    description="Only the fields sent are changed. Sending null clears an optional field.",
    responses={**AUTH_ERRORS, **NOT_FOUND, **INVALID},
)
def update_profile(
    request: UserProfileUpdate,
    user: AuthenticatedUser = Depends(get_current_authenticated_user),
    db: Session = Depends(get_db),
):
    try:
        return user_service.update_profile(db, user.auth_user_id, request.model_dump(exclude_unset=True))
    except PROFILE_ERRORS as exc:
        raise http_error(exc) from exc


@router.delete(
    "/profile",
    response_model=MessageResponse,
    summary="Deactivate the caller's profile",
    description=(
        "Sets is_active to false and keeps the record. The Authentication Service account is "
        "not changed. Afterwards every profile, address and account operation returns 403. "
        "Same effect as PATCH /api/users/account/deactivate."
    ),
    responses={**AUTH_ERRORS, **NOT_FOUND},
)
def deactivate_profile(
    user: AuthenticatedUser = Depends(get_current_authenticated_user),
    db: Session = Depends(get_db),
):
    try:
        user_service.deactivate_profile(db, user.auth_user_id)
    except PROFILE_ERRORS as exc:
        raise http_error(exc) from exc
    return MessageResponse(message="User profile deactivated")
