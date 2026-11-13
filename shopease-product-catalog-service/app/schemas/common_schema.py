"""Schemas shared by every router: errors, messages, and the service endpoints."""

import math
import re
from typing import Annotated, Generic, TypeVar
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
# Keeps line breaks and tabs, which are normal in long descriptions.
_CONTROL_EXCEPT_WHITESPACE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _single_line(value: str) -> str:
    if _CONTROL_CHARACTERS.search(value):
        raise ValueError("must not contain control characters")
    return value


def _multi_line(value: str) -> str:
    if _CONTROL_EXCEPT_WHITESPACE.search(value):
        raise ValueError("must not contain control characters")
    return value


def _validate_image_url(value: str) -> str:
    if any(character.isspace() for character in value) or _CONTROL_CHARACTERS.search(value):
        raise ValueError("must not contain spaces or control characters")
    if not value.lower().startswith(("http://", "https://")):
        raise ValueError("must be an http(s) URL")
    try:
        url = urlsplit(value)
        url.port  # raises ValueError for an invalid port
    except ValueError as exc:
        raise ValueError("is not a valid URL") from exc
    if not url.hostname:
        raise ValueError("URL must include a host")
    if url.username or url.password:
        raise ValueError("URL must not contain credentials")
    return value


_WHITESPACE_RUN = re.compile(r"\s+")


def _display_name(value: str) -> str:
    # Use after SingleLineText: control characters are already refused, so only spaces collapse here.
    value = _WHITESPACE_RUN.sub(" ", value).strip()
    if not any(character.isalnum() for character in value):
        raise ValueError("must contain at least one letter or digit")
    return value


SingleLineText = AfterValidator(_single_line)
# Names shown to customers: inner runs of spaces become one, and at least one letter or digit.
DisplayName = AfterValidator(_display_name)
MultiLineText = AfterValidator(_multi_line)
ImageUrl = Annotated[str, Field(max_length=500), AfterValidator(_validate_image_url)]


ItemT = TypeVar("ItemT")


# Generic[...] rather than "class Page[ItemT]": that syntax needs Python 3.12, the target is 3.11.
class Page(BaseModel, Generic[ItemT]):
    """One page of a list: the items, the total number of matches, and the paging position."""

    items: list[ItemT]
    total: int = Field(description="Number of records matching the filters, on all pages")
    page: int = Field(description="Current page, starting at 1")
    page_size: int = Field(description="Maximum number of items per page")
    total_pages: int = Field(description="Number of pages; 0 when nothing matches")

    @classmethod
    def build(cls, items: list, total: int, query: "PageQuery") -> "Page":
        """A page past the last one is valid: it has no items, and total still counts every match."""
        return cls(items=items, total=total, page=query.page, page_size=query.page_size,
                   total_pages=math.ceil(total / query.page_size))


MAX_PAGE = 100_000
MAX_PAGE_SIZE = 100


class PageQuery(BaseModel):
    """Paging query parameters. Unknown parameters are refused (422), so a misspelt one such as
    `pagesize` is reported instead of silently ignored."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1, le=MAX_PAGE, description="Page number, starting at 1")
    page_size: int = Field(default=20, ge=1, le=MAX_PAGE_SIZE,
                           description=f"Items per page, 1 to {MAX_PAGE_SIZE}")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


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
