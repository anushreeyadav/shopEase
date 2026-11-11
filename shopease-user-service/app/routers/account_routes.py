"""HTTP layer for the caller's account: request handling only, no business logic.

Every route depends on get_current_authenticated_user and acts only on that caller.
Deactivation changes the local User Service profile, never the Authentication Service account.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, get_current_authenticated_user
from app.database.connection import get_db
from app.routers.user_routes import AUTH_ERRORS, INVALID, NOT_FOUND, PROFILE_ERRORS, http_error
from app.schemas.account_schema import (
    AccountDeactivationResponse,
    AccountResponse,
    AuthenticationAccountResponse,
    ContactUpdate,
)
from app.schemas.user_schema import ErrorResponse, UserProfileResponse
from app.services import account_service

router = APIRouter(prefix="/users/account", tags=["Account"])


@router.get(
    "",
    response_model=AccountResponse,
    summary="Get the caller's account and profile",
    description=(
        "The Authentication Service account (from the verified token) and the User Service profile. "
        "profile is null and profile_status is NOT_CREATED until a profile is created."
    ),
    responses=AUTH_ERRORS,
)
def read_account(
    user: AuthenticatedUser = Depends(get_current_authenticated_user),
    db: Session = Depends(get_db),
):
    try:
        overview = account_service.get_account(db, user)
    except PROFILE_ERRORS as exc:
        raise http_error(exc) from exc
    return AccountResponse(
        authentication_account=AuthenticationAccountResponse(
            auth_user_id=user.auth_user_id, full_name=user.full_name, email=user.email, role=user.role
        ),
        profile_status="ACTIVE" if overview.profile is not None else "NOT_CREATED",
        profile=overview.profile,
    )


@router.patch(
    "/contact",
    response_model=UserProfileResponse,
    summary="Update the caller's contact phone number",
    description=(
        "Body: {\"phone_number\": \"...\"}, or null to clear it. The email address belongs to the "
        "Authentication Service and cannot be changed here."
    ),
    responses={**AUTH_ERRORS, **NOT_FOUND, **INVALID},
)
def update_contact(
    request: ContactUpdate,
    user: AuthenticatedUser = Depends(get_current_authenticated_user),
    db: Session = Depends(get_db),
):
    try:
        return account_service.update_contact(db, user.auth_user_id, request.phone_number)
    except PROFILE_ERRORS as exc:
        raise http_error(exc) from exc


@router.patch(
    "/deactivate",
    response_model=AccountDeactivationResponse,
    summary="Deactivate the caller's User Service profile",
    description=(
        "Sets the local profile's is_active to false and keeps the profile and its addresses. "
        "The Authentication Service account is not deleted or changed: the user can still log in. "
        "Afterwards every profile, address and account operation returns 403."
    ),
    responses={
        **AUTH_ERRORS,
        **NOT_FOUND,
        403: {"model": ErrorResponse, "description": "Inactive Authentication Service user, or already deactivated"},
    },
)
def deactivate_account(
    user: AuthenticatedUser = Depends(get_current_authenticated_user),
    db: Session = Depends(get_db),
):
    try:
        account_service.deactivate_account(db, user.auth_user_id)
    except PROFILE_ERRORS as exc:
        raise http_error(exc) from exc
    return AccountDeactivationResponse(
        message="User profile deactivated", profile_status="DEACTIVATED", authentication_account_changed=False
    )
