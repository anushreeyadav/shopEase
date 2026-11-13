"""Request and response schemas for categories.

Request schemas use extra="forbid": unknown fields, including id and timestamps, are rejected with 422.

Name rules (all requests): surrounding spaces are removed and inner runs of whitespace become one
space; 1-100 characters; no control characters; at least one letter or digit. Uniqueness, which
ignores letter case, is checked by the service against stored data.
"""

from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.security import MAX_DB_INT
from app.models.category_model import CATEGORY_NAME_LENGTH
from app.schemas.common_schema import DisplayName, MultiLineText, SingleLineText

CATEGORY_DESCRIPTION_LENGTH = 5000
CategoryName = Annotated[
    str,
    Field(min_length=1, max_length=CATEGORY_NAME_LENGTH, description="Unique, ignoring letter case",
          examples=["Running Shoes"]),
    SingleLineText,
    DisplayName,
]
CategoryDescription = Annotated[
    str,
    Field(max_length=CATEGORY_DESCRIPTION_LENGTH, examples=["Road and trail running shoes"]),
    MultiLineText,
]
CategoryId = Annotated[int, Field(ge=1, le=MAX_DB_INT)]


class CategoryCreate(BaseModel):
    """POST /api/categories/. Only name is required. New categories are active."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        json_schema_extra={"examples": [{"name": "Running Shoes", "description": "Road and trail running shoes"}]},
    )

    name: CategoryName
    description: CategoryDescription | None = None


class CategoryReplace(BaseModel):
    """PUT /api/categories/{id}: the complete new state. Every field must be sent.

    description may be null, which clears it. is_active false deactivates the category.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        json_schema_extra={"examples": [
            {"name": "Running Shoes", "description": "Road and trail running shoes", "is_active": True},
        ]},
    )

    name: CategoryName
    description: CategoryDescription | None = Field(description="Send null to clear the description")
    is_active: bool = Field(description="false deactivates the category and hides it, and its products, "
                                        "from public listings")


class CategoryUpdate(BaseModel):
    """PATCH /api/categories/{id}: only the fields sent are changed.

    Sending null clears description. name and is_active cannot be null.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        json_schema_extra={"examples": [{"is_active": False}, {"description": "Updated description"}]},
    )

    name: CategoryName | None = None
    description: CategoryDescription | None = None
    is_active: bool | None = None

    @field_validator("name", "is_active")
    @classmethod
    def not_null(cls, value):
        # Runs only when the field is sent, so leaving it out is still allowed.
        if value is None:
            raise ValueError("cannot be null")
        return value

    @model_validator(mode="after")
    def at_least_one_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Send at least one field to update")
        return self


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
