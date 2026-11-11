"""Request and response schemas for the caller's account."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.user_schema import PhoneNumber, UserProfileResponse


class AuthenticationAccountResponse(BaseModel):
    """The caller's account in the Authentication Service, as its verify-token response reported it."""

    auth_user_id: int
    full_name: str
    email: str
    role: str
    status: Literal["ACTIVE"] = Field(
        "ACTIVE", description="Always ACTIVE here: an inactive account is rejected with 403 before this point"
    )


class AccountResponse(BaseModel):
    authentication_account: AuthenticationAccountResponse
    profile_status: Literal["ACTIVE", "NOT_CREATED"] = Field(
        description="The User Service profile. A deactivated profile gets 403 instead of this response"
    )
    profile: UserProfileResponse | None


class ContactUpdate(BaseModel):
    """PATCH /api/users/account/contact. phone_number must be sent; null clears it.

    The email address cannot be changed here: it belongs to the Authentication Service.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    phone_number: PhoneNumber | None


class AccountDeactivationResponse(BaseModel):
    message: str
    profile_status: Literal["DEACTIVATED"]
    authentication_account_changed: Literal[False] = Field(
        description="Always false: the Authentication Service account is not modified"
    )
