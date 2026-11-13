"""Request and response schemas for products.

Separate schemas per operation:
  ProductCreate   POST   /api/products/              new product; initial_stock optional
  ProductReplace  PUT    /api/products/{id}          every editable field required
  ProductUpdate   PATCH  /api/products/{id}          only the fields sent
  ProductResponse        every response
  ProductListQuery GET   /api/products/              search, filters, paging and sorting

Request schemas use extra="forbid": unknown or read-only fields (id, stock_quantity, timestamps)
are rejected with 422. stock_quantity is never accepted: stock changes only through inventory
transactions, so every change is recorded.

Money is Decimal, never float. Prices may be sent as a JSON string ("19.99", recommended) or a
number, are at least 0 with at most 2 decimal places and 8 digits before the point
(DECIMAL(10, 2)), and are returned as strings with exactly two decimal places.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from app.models.product_model import BRAND_LENGTH, PRODUCT_NAME_LENGTH, SKU_LENGTH
from app.schemas.category_schema import CategoryId
from app.schemas.common_schema import DisplayName, ImageUrl, MultiLineText, Page, PageQuery, SingleLineText

MAX_STOCK = 1_000_000_000  # well inside a signed 32-bit INT, so stock + quantity cannot overflow
PRODUCT_DESCRIPTION_LENGTH = 10_000
CENT = Decimal("0.01")


def _normalize_sku(value: str) -> str:
    return value.upper()


def _two_places(value: Decimal) -> Decimal:
    # "19.5" -> 19.50 and "-0" -> 0.00, so the response shows exactly what the database stores.
    return value.quantize(CENT) if value != 0 else Decimal("0.00")


# Letters, digits and hyphens, starting with a letter or digit: "TSHIRT-RED-M". Stored upper-case.
Sku = Annotated[
    str,
    Field(min_length=1, max_length=SKU_LENGTH, pattern=r"^[A-Za-z0-9][A-Za-z0-9\-]*$",
          description="Letters, digits and hyphens. Stored upper-case; unique, ignoring case.",
          examples=["TSHIRT-RED-M"]),
    AfterValidator(_normalize_sku),
]
ProductName = Annotated[
    str,
    Field(min_length=1, max_length=PRODUCT_NAME_LENGTH, examples=["Red Cotton T-Shirt"]),
    SingleLineText,
    DisplayName,
]
ProductDescription = Annotated[str, Field(max_length=PRODUCT_DESCRIPTION_LENGTH), MultiLineText]
Brand = Annotated[str, Field(min_length=1, max_length=BRAND_LENGTH, examples=["Basics"]), SingleLineText, DisplayName]
# Up to 99,999,999.99; matches DECIMAL(10, 2).
Money = Annotated[
    Decimal,
    Field(ge=0, max_digits=10, decimal_places=2, allow_inf_nan=False, examples=["19.99"]),
    AfterValidator(_two_places),
]
StockQuantity = Annotated[int, Field(ge=0, le=MAX_STOCK)]


def check_discount(price: Decimal, discount_price: Decimal | None) -> None:
    """The same rule as the database's ck_products_discount_price_valid constraint.

    A discount equal to the price would not be a discount, so it must be strictly lower.
    """
    if discount_price is not None and discount_price >= price:
        raise ValueError("discount_price must be lower than price")


def _discount_below_sent_price(value: Decimal | None, info: ValidationInfo) -> Decimal | None:
    """Field validator body: price is declared before discount_price, so a valid price is in info.data.

    Reported on the discount_price field. If price itself was invalid, its own error is reported.
    """
    price = info.data.get("price")
    if price is not None:
        check_discount(price, value)
    return value


_EXAMPLE = {
    "category_id": 1,
    "name": "Red Cotton T-Shirt",
    "description": "Cotton, regular fit",
    "sku": "TSHIRT-RED-M",
    "price": "19.99",
    "discount_price": "14.99",
    "image_url": "https://cdn.example.com/products/tshirt-red.png",
    "brand": "Basics",
}


class ProductCreate(BaseModel):
    """POST /api/products/. Required: category_id, name, sku, price.

    The category must exist and be active. initial_stock, when above 0, is recorded as the
    product's first IN inventory transaction. New products are active.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid",
                              json_schema_extra={"examples": [_EXAMPLE | {"initial_stock": 25}]})

    category_id: CategoryId
    name: ProductName
    description: ProductDescription | None = None
    sku: Sku
    price: Money
    discount_price: Money | None = Field(default=None, description="Must be lower than price")
    image_url: ImageUrl | None = None
    brand: Brand | None = None
    initial_stock: StockQuantity = Field(default=0, description="Opening stock, recorded as an IN transaction")

    @field_validator("discount_price")
    @classmethod
    def discount_below_price(cls, value: Decimal | None, info: ValidationInfo) -> Decimal | None:
        return _discount_below_sent_price(value, info)


class ProductReplace(BaseModel):
    """PUT /api/products/{id}: the complete new state. Every field must be sent.

    description, discount_price, image_url and brand may be null, which clears them.
    is_active false deactivates the product. Stock is not part of it.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid",
                              json_schema_extra={"examples": [_EXAMPLE | {"is_active": True}]})

    category_id: CategoryId
    name: ProductName
    description: ProductDescription | None
    sku: Sku
    price: Money
    discount_price: Money | None = Field(description="Must be lower than price; null for no discount")
    image_url: ImageUrl | None
    brand: Brand | None
    is_active: bool

    @field_validator("discount_price")
    @classmethod
    def discount_below_price(cls, value: Decimal | None, info: ValidationInfo) -> Decimal | None:
        return _discount_below_sent_price(value, info)


class ProductUpdate(BaseModel):
    """PATCH /api/products/{id}: only the fields sent are changed.

    Sending null clears description, discount_price, image_url or brand. category_id, name, sku,
    price and is_active cannot be null. A discount is checked against the stored price when only
    one of the two is sent.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid",
                              json_schema_extra={"examples": [{"price": "17.99"}, {"is_active": False},
                                                              {"discount_price": None}]})

    category_id: CategoryId | None = None
    name: ProductName | None = None
    description: ProductDescription | None = None
    sku: Sku | None = None
    price: Money | None = None
    discount_price: Money | None = None
    image_url: ImageUrl | None = None
    brand: Brand | None = None
    is_active: bool | None = None

    @field_validator("category_id", "name", "sku", "price", "is_active")
    @classmethod
    def not_null(cls, value):
        # Runs only when the field is sent, so leaving it out is still allowed.
        if value is None:
            raise ValueError("cannot be null")
        return value

    @field_validator("discount_price")
    @classmethod
    def discount_below_price(cls, value: Decimal | None, info: ValidationInfo) -> Decimal | None:
        # When price is not sent, the service checks the discount against the stored price.
        return _discount_below_sent_price(value, info)

    @model_validator(mode="after")
    def at_least_one_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Send at least one field to update")
        return self


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int
    name: str
    description: str | None
    sku: str
    price: Decimal
    discount_price: Decimal | None
    effective_price: Decimal = Field(description="discount_price when set, otherwise price")
    stock_quantity: int = Field(description="Current stock; changed only through /api/inventory")
    in_stock: bool
    image_url: str | None
    brand: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


ProductListResponse = Page[ProductResponse]

# Sorting is allowed only on these columns. The value picks a column from a fixed mapping in the
# service, so no text from the request ever reaches the SQL.
SortBy = Literal["name", "price", "created_at"]
SortOrder = Literal["asc", "desc"]
Availability = Literal["in_stock", "out_of_stock"]
SEARCH_LENGTH = 100


class ProductListQuery(PageQuery):
    """Query parameters of GET /api/products/. Every filter is optional; the filters sent are
    combined with AND. Unknown parameters are refused with 422."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    search: str | None = Field(
        default=None, min_length=1, max_length=SEARCH_LENGTH, examples=["mobile"],
        description="Part of the product name or SKU, ignoring case. % and _ match themselves.",
    )
    category_id: CategoryId | None = Field(default=None, description="Only products in this category")
    min_price: Money | None = Field(default=None, description="Lowest price, inclusive (the normal price, "
                                                              "not the discount price)")
    max_price: Money | None = Field(default=None, description="Highest price, inclusive. Not below min_price")
    availability: Availability | None = Field(
        default=None, description="`in_stock`: stock above 0. `out_of_stock`: stock 0. Leave out for both.",
    )
    brand: str | None = Field(default=None, min_length=1, max_length=BRAND_LENGTH,
                              description="Exact brand, ignoring case")
    sort_by: SortBy = Field(default="name", description="Sort column: name, price or created_at")
    sort_order: SortOrder = Field(default="asc", description="asc or desc")
    include_inactive: bool = Field(default=False, description="Also return inactive products and products in "
                                                              "inactive categories. Needs an ADMIN token.")

    @field_validator("max_price")
    @classmethod
    def max_not_below_min(cls, value: Decimal | None, info: ValidationInfo) -> Decimal | None:
        minimum = info.data.get("min_price")
        if value is not None and minimum is not None and value < minimum:
            raise ValueError("max_price must not be lower than min_price")
        return value
