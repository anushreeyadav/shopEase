# API endpoint reference

ShopEase Product Catalog Service 1.0.0, base URL `http://127.0.0.1:8006`. The full specification is
[openapi.json](openapi.json), identical to the live `/openapi.json` (checked in the final audit, 12 November
2026). Worked request and response examples are in `Word_Documents/API_Documentation.docx`.

Authentication: `Authorization: Bearer <access token from the Authentication Service>`. ADMIN = role `ADMIN`.
Customers have the role `USER`. Errors: `{"detail": "..."}`, plus `errors: [{field, message}]` for 422.

## Service

| Method | Path | Access | Success | Errors |
|---|---|---|---|---|
| GET | `/` | Public | 200 `{"service", "version", "docs_url"}` | — |
| GET | `/health` | Public | 200 `{"status":"ok","service":...,"version":"1.0.0"}` | — |
| GET | `/health/db` | Public | 200 `{"status":"ok","database":"connected"}` | 503 |

## Categories

| Method | Path | Access | Query / body | Success | Errors |
|---|---|---|---|---|---|
| GET | `/api/categories/` | Public | `include_inactive` (ADMIN) | 200 list | 401, 403, 422 |
| GET | `/api/categories/{category_id}` | Public | `include_inactive` (ADMIN) | 200 | 401, 403, 404, 422 |
| POST | `/api/categories/` | ADMIN | `name` (required), `description` | 201 | 400, 401, 403, 409, 422 |
| PUT | `/api/categories/{category_id}` | ADMIN | `name`, `description`, `is_active` (all required) | 200 | 400, 401, 403, 404, 409, 422 |
| PATCH | `/api/categories/{category_id}` | ADMIN | any of `name`, `description`, `is_active` | 200 | 400, 401, 403, 404, 409, 422 |
| DELETE | `/api/categories/{category_id}` | ADMIN | — | 200 (only when empty) | 401, 403, 404, 409, 422 |

## Products

| Method | Path | Access | Query / body | Success | Errors |
|---|---|---|---|---|---|
| GET | `/api/products/` | Public | `search`, `category_id`, `min_price`, `max_price`, `availability` (`in_stock`/`out_of_stock`), `brand`, `page` (1–100000), `page_size` (1–100), `sort_by` (`name`/`price`/`created_at`), `sort_order` (`asc`/`desc`), `include_inactive` (ADMIN) | 200 `{items, total, page, page_size, total_pages}` | 401, 403, 422 |
| GET | `/api/products/{product_id}` | Public | `include_inactive` (ADMIN) | 200 | 401, 403, 404, 422 |
| POST | `/api/products/` | ADMIN | `category_id`, `name`, `sku`, `price` (required); `description`, `discount_price`, `image_url`, `brand`, `initial_stock` | 201 | 400, 401, 403, 409, 422 |
| PUT | `/api/products/{product_id}` | ADMIN | every editable field | 200 | 400, 401, 403, 404, 409, 422 |
| PATCH | `/api/products/{product_id}` | ADMIN | any editable field (`stock_quantity` refused) | 200 | 400, 401, 403, 404, 409, 422 |
| DELETE | `/api/products/{product_id}` | ADMIN | — | 200 (deactivated, row kept) | 401, 403, 404, 422 |

## Inventory (all ADMIN)

| Method | Path | Query / body | Success | Errors |
|---|---|---|---|---|
| GET | `/api/inventory/{product_id}` | — | 200 `{product_id, sku, name, stock_quantity, low_stock_threshold, is_low_stock}` | 401, 403, 404, 422 |
| POST | `/api/inventory/{product_id}/stock-in` | `{"quantity": 1..1000000000, "remarks": "..."}` | 201 `{transaction, stock}` | 400, 401, 403, 404, 409, 422 |
| POST | `/api/inventory/{product_id}/stock-out` | same | 201 `{transaction, stock}` | 400, 401, 403, 404, 409 `Insufficient stock: N available, M requested`, 422 |
| GET | `/api/inventory/{product_id}/history` | `page`, `page_size`, `transaction_type` (`IN`/`OUT`) | 200 page of transactions, newest first | 401, 403, 404, 422 |
| GET | `/api/inventory/low-stock` | — | 200 list, lowest stock first | 401, 403 |

Every route that checks a token can also answer **503** when the Authentication Service cannot verify it.
