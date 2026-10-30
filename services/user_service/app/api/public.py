"""Public /api/users routes (rest_api_notes.md §3.3). Reached through the gateway.

Every route authenticates the caller from a verified access token. Authorization happens
here, not only at the gateway: customers reach only their own data; admins may read any
profile through GET /api/users/{user_id}.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app import profiles
from app.dependencies import DbSession
from app.models import UserProfile
from app.schemas import AddressPage, AddressRead, AddressWrite, ProfileRead, ProfileUpdate
from shopease_shared import ShopEaseError
from shopease_shared.security import AdminUser, CurrentUser

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=ProfileRead, summary="Get the caller's profile (created on first access)")
def get_me(user: CurrentUser, session: DbSession) -> ProfileRead:
    return ProfileRead.model_validate(profiles.get_or_create_profile(session, user.user_id))


@router.patch("/me", response_model=ProfileRead, summary="Update the caller's profile")
def update_me(body: ProfileUpdate, user: CurrentUser, session: DbSession) -> ProfileRead:
    changes = body.model_dump(exclude_unset=True)
    return ProfileRead.model_validate(profiles.update_profile(session, user.user_id, changes))


@router.get("/me/addresses", response_model=AddressPage, summary="List the caller's addresses")
def list_addresses(
    user: CurrentUser,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AddressPage:
    items, total = profiles.list_addresses(session, user.user_id, limit, offset)
    return AddressPage(
        items=[AddressRead.model_validate(a) for a in items], total=total, limit=limit, offset=offset
    )


@router.post("/me/addresses", status_code=201, response_model=AddressRead, summary="Add an address")
def create_address(body: AddressWrite, user: CurrentUser, session: DbSession, response: Response) -> AddressRead:
    address = profiles.create_address(session, user.user_id, body.model_dump())
    response.headers["Location"] = f"/api/users/me/addresses/{address.id}"
    return AddressRead.model_validate(address)


@router.put("/me/addresses/{address_id}", response_model=AddressRead, summary="Replace one of the caller's addresses")
def replace_address(address_id: UUID, body: AddressWrite, user: CurrentUser, session: DbSession) -> AddressRead:
    return AddressRead.model_validate(
        profiles.replace_address(session, user.user_id, address_id, body.model_dump())
    )


@router.delete("/me/addresses/{address_id}", status_code=204, summary="Delete one of the caller's addresses")
def delete_address(address_id: UUID, user: CurrentUser, session: DbSession) -> None:
    profiles.delete_address(session, user.user_id, address_id)


@router.get("/{user_id}", response_model=ProfileRead, summary="Get any user's profile (admin)")
def get_user(user_id: UUID, admin: AdminUser, session: DbSession) -> ProfileRead:
    profile = session.get(UserProfile, user_id)
    if profile is None:
        raise ShopEaseError(404, "PROFILE_NOT_FOUND", "No profile for this user.")
    return ProfileRead.model_validate(profile)
