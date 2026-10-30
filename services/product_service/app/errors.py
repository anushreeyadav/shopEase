"""product_service error responses (ShopEase envelope, rest_api_notes.md §1.8)."""

import uuid
from typing import Any

from shopease_shared import ShopEaseError


def product_not_found(product_id: uuid.UUID) -> ShopEaseError:
    return ShopEaseError(404, "PRODUCT_NOT_FOUND", f"Product {product_id} was not found.")


def category_not_found(category_id: uuid.UUID) -> ShopEaseError:
    return ShopEaseError(404, "CATEGORY_NOT_FOUND", f"Category {category_id} was not found.")


def reservation_not_found(order_id: uuid.UUID) -> ShopEaseError:
    return ShopEaseError(404, "RESERVATION_NOT_FOUND", f"No stock reservation for order {order_id}.")


def conflict(code: str, message: str, details: list[dict[str, Any]] | None = None) -> ShopEaseError:
    return ShopEaseError(409, code, message, details)
