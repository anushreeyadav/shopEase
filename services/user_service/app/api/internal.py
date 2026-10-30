"""Internal /internal/users routes (rest_api_notes.md Part 4). Never routed by the gateway.

Requires both a service token with scope `addresses:read` (which service is calling) and
the end user's forwarded access token in X-User-Token (on whose behalf). The address must
belong to that user, so a caller can't read arbitrary addresses by guessing IDs.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app import profiles
from app.dependencies import DbSession
from app.schemas import AddressRead
from shopease_shared.security import ForwardedUser, Principal, require_scope

router = APIRouter(prefix="/internal/users", tags=["internal"])


@router.get(
    "/{user_id}/addresses/{address_id}",
    response_model=AddressRead,
    summary="Delivery address lookup for order_service (scope addresses:read)",
)
def get_address(
    user_id: UUID,
    address_id: UUID,
    service: Annotated[Principal, Depends(require_scope("addresses:read"))],
    end_user: ForwardedUser,
    session: DbSession,
) -> AddressRead:
    if end_user.user_id != user_id:
        raise profiles.address_not_found()
    return AddressRead.model_validate(profiles.get_owned_address(session, user_id, address_id))
