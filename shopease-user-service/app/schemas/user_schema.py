"""Request and response schemas for user profiles and the service endpoints.

No request schema has an auth_user_id, id, is_active, email, or password field, and
extra="forbid" rejects them with 422: the owner always comes from the verified token,
and credentials belong to the Authentication Service.
"""

import re
from datetime import date, datetime
from typing import Annotated, Self
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.phone_utils import normalize_phone_number
from app.models.user_model import Gender

FULL_NAME_MAX_LENGTH = 255
PROFILE_IMAGE_MAX_LENGTH = 500
EARLIEST_DATE_OF_BIRTH = date(1900, 1, 1)
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_SAFE_IMAGE_PATH = re.compile(r"/[A-Za-z0-9._\-/]+")


def _validate_full_name(value: str) -> str:
    if _CONTROL_CHARACTERS.search(value):
        raise ValueError("full_name must not contain control characters")
    return value


def _validate_date_of_birth(value: date) -> date:
    if value > date.today():
        raise ValueError("date_of_birth cannot be in the future")
    if value < EARLIEST_DATE_OF_BIRTH:
        raise ValueError(f"date_of_birth cannot be before {EARLIEST_DATE_OF_BIRTH.isoformat()}")
    return value


def _validate_profile_image(value: str) -> str:
    """Accept an http(s) URL, or a server path such as /media/avatars/7.png."""
    if any(character.isspace() for character in value) or _CONTROL_CHARACTERS.search(value):
        raise ValueError("profile_image must not contain spaces or control characters")

    if value.lower().startswith(("http://", "https://")):
        try:
            url = urlsplit(value)
            url.port  # raises ValueError for an invalid port
        except ValueError as exc:
            raise ValueError("profile_image is not a valid URL") from exc
        if not url.hostname:
            raise ValueError("profile_image URL must include a host")
        if url.username or url.password:
            raise ValueError("profile_image URL must not contain credentials")
        return value

    if value.startswith("/") and not value.startswith("//"):
        if not _SAFE_IMAGE_PATH.fullmatch(value) or ".." in value.split("/"):
            raise ValueError("profile_image path may contain only letters, digits, '.', '_', '-' and '/'")
        if not value.lower().endswith(IMAGE_EXTENSIONS):
            raise ValueError("profile_image path must end with " + ", ".join(IMAGE_EXTENSIONS))
        return value

    raise ValueError("profile_image must be an http(s) URL or a path starting with /")


FullName = Annotated[
    str, Field(min_length=1, max_length=FULL_NAME_MAX_LENGTH), AfterValidator(_validate_full_name)
]
# Accepts common formats ("+91 98765-43210", "(020) 7946 0958") and stores digits only,
# with an optional leading "+".
PhoneNumber = Annotated[str, Field(max_length=30), AfterValidator(normalize_phone_number)]
DateOfBirth = Annotated[date, AfterValidator(_validate_date_of_birth)]
ProfileImage = Annotated[
    str, Field(max_length=PROFILE_IMAGE_MAX_LENGTH), AfterValidator(_validate_profile_image)
]


class UserProfileCreate(BaseModel):
    """POST /api/users/profile. Only full_name is required."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    full_name: FullName
    phone_number: PhoneNumber | None = None
    date_of_birth: DateOfBirth | None = None
    gender: Gender | None = None
    profile_image: ProfileImage | None = None


class UserProfileReplace(UserProfileCreate):
    """PUT /api/users/profile: a full replacement. An omitted optional field is set to null."""


class UserProfileUpdate(BaseModel):
    """PATCH /api/users/profile: only the fields sent are changed.

    Sending null clears an optional field. full_name cannot be cleared.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    full_name: FullName | None = None
    phone_number: PhoneNumber | None = None
    date_of_birth: DateOfBirth | None = None
    gender: Gender | None = None
    profile_image: ProfileImage | None = None

    @field_validator("full_name")
    @classmethod
    def full_name_cannot_be_cleared(cls, value: str | None) -> str:
        # Runs only when full_name is sent, so leaving it out is still allowed.
        if value is None:
            raise ValueError("full_name cannot be null")
        return value

    @model_validator(mode="after")
    def at_least_one_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Send at least one field to update")
        return self


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    auth_user_id: int
    full_name: str
    phone_number: str | None
    date_of_birth: date | None
    gender: Gender | None
    profile_image: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    message: str


class ErrorResponse(BaseModel):
    detail: str


class FieldError(BaseModel):
    field: str
    message: str


class ValidationErrorResponse(BaseModel):
    detail: str
    errors: list[FieldError]


class RootResponse(BaseModel):
    service: str
    version: str
    docs_url: str | None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class DatabaseHealthResponse(BaseModel):
    status: str
    database: str
