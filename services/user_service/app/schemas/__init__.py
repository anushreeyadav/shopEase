"""Pydantic request/response schemas for user_service (rest_api_notes.md §3.3)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    full_name: str | None
    phone: str | None
    contact_email: EmailStr | None
    created_at: datetime
    updated_at: datetime


class ProfileUpdate(BaseModel):
    """PATCH body: only the fields sent are changed."""

    model_config = ConfigDict(json_schema_extra={"examples": [{'full_name': 'Asha Rao', 'phone': '+91-90000-00000'}]}, extra="forbid")

    full_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=32)
    contact_email: EmailStr | None = None


class AddressWrite(BaseModel):
    """Body for POST and PUT (PUT replaces the whole address)."""

    model_config = ConfigDict(json_schema_extra={"examples": [{'label': 'Home', 'line1': '12 Example Street', 'line2': 'Flat 4B', 'city': 'Pune', 'state': 'Maharashtra', 'postal_code': '411001', 'country': 'IN', 'is_default': True}]}, extra="forbid")

    label: str | None = Field(default=None, max_length=50)
    line1: str = Field(min_length=1, max_length=200)
    line2: str | None = Field(default=None, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str = Field(min_length=1, max_length=20)
    country: str = Field(pattern=r"^[A-Z]{2}$")
    is_default: bool = False


class AddressRead(AddressWrite):
    model_config = ConfigDict(from_attributes=True, extra="ignore", json_schema_extra=None)

    address_id: uuid.UUID = Field(validation_alias="id")
    created_at: datetime
    updated_at: datetime


class AddressPage(BaseModel):
    """Pagination envelope (rest_api_notes.md §1.6)."""

    items: list[AddressRead]
    total: int
    limit: int
    offset: int
