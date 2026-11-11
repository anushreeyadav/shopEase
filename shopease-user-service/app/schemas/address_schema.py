"""Request and response schemas for user addresses.

No request schema has an id, user_id, or auth_user_id field, and extra="forbid" rejects them
with 422: the owner always comes from the verified token. is_default can be set when an
address is created; after that only the set-default endpoint changes it.
"""

import re
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.models.address_model import AddressType
from app.schemas.user_schema import FullName, PhoneNumber

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_POSTAL_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 \-]*[A-Za-z0-9]")


def _no_control_characters(value: str) -> str:
    if _CONTROL_CHARACTERS.search(value):
        raise ValueError("must not contain control characters")
    return value


def _validate_postal_code(value: str) -> str:
    if not _POSTAL_CODE.fullmatch(value):
        raise ValueError("postal_code may contain only letters, digits, spaces and '-'")
    return value


AddressLine = Annotated[str, Field(min_length=1, max_length=255), AfterValidator(_no_control_characters)]
Place = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(_no_control_characters)]
PostalCode = Annotated[str, Field(min_length=3, max_length=20), AfterValidator(_validate_postal_code)]


class AddressFields(BaseModel):
    """The editable fields of an address."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    address_type: AddressType = Field(AddressType.HOME, description="HOME, OFFICE or OTHER")
    full_name: FullName = Field(description="Recipient's name")
    phone_number: PhoneNumber
    address_line_1: AddressLine
    address_line_2: AddressLine | None = None
    city: Place
    state: Place
    country: Place
    postal_code: PostalCode


class AddressCreate(AddressFields):
    """POST /api/users/addresses. The caller's first address always becomes the default."""

    is_default: bool = Field(False, description="Make this the default address, replacing the old default")


class AddressReplace(AddressFields):
    """PUT /api/users/addresses/{address_id}: a full replacement.

    An omitted address_line_2 is set to null and an omitted address_type to HOME.
    is_default is not accepted here; use PATCH .../default.
    """


class AddressResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    address_type: AddressType
    full_name: str
    phone_number: str
    address_line_1: str
    address_line_2: str | None
    city: str
    state: str
    country: str
    postal_code: str
    is_default: bool
    created_at: datetime
