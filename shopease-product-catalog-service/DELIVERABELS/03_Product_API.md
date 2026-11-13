# Product Management API

| | |
|---|---|
| Task | 7: product management APIs |
| Date | 12 November 2026 |
| Code | `app/routers/product_routes.py` (HTTP), `app/services/product_service.py` (rules, transactions), `app/schemas/product_schema.py` (validation) |
| Tests | `tests/test_product_api.py`: 111 tests, all passed on SQLite and on MySQL 8.4 |
| API evidence | `Test_Results/product_api_logs/02_api_transcript.md`: 54 recorded requests, all with the expected status |
| OpenAPI export | `API_Documentation/openapi.json`, taken from the running container |

## 1. Requirements

| # | Requirement | How it is met | Evidence (transcript step / test) |
|---|---|---|---|
| 1 | ADMIN creates, updates, partially updates, deletes | `require_admin` on POST, PUT, PATCH, DELETE | "Admin creates…", "Admin replaces…(PUT)", "…(PATCH)", "Admin deletes…" |
| 2 | Customers view active products | GET routes are public; the customer role is `USER` | "Customer lists products", "Customer gets a product" |
| 3 | Names and required fields validated | Required: `category_id`, `name`, `sku`, `price`. Names trimmed and collapsed, need a letter or digit | "Required fields missing"; `test_required_fields_are_listed`, `test_invalid_fields_get_clear_messages` |
| 4 | Unique SKU | Checked first; the unique constraint catches races; case is ignored | "Duplicate SKU, different letter case", "PUT to the other product's SKU" |
| 5 | Category exists and is active | Checked on create and on category change, with the row locked | "Category does not exist", "Category is inactive", "PATCH into an inactive category" |
| 6 | Decimal price and discount | `Decimal` end to end, `DECIMAL(10,2)` in MySQL, returned as `"19.50"` | "Admin creates a product…" (`"19.5"` → `"19.50"`) |
| 7 | No negative prices | `ge=0` in the schema, CHECK in the database | "Negative price" |
| 8 | Discount does not exceed price | Must be strictly lower, also against the stored price in PATCH | "Discount equal to price", "PATCH a discount above the stored price" |
| 9 | No negative stock | `stock_quantity` not accepted; `initial_stock ≥ 0`; CHECK in the database; stock-out cannot overdraw | "Negative initial stock", "stock_quantity cannot be set", "PATCH stock directly" |
| 10 | Activation and deactivation | `is_active` via PUT/PATCH; DELETE deactivates | "Admin deletes (deactivates)…", "Admin reactivates it" |
| 11 | Customer listings hide inactive products and products in inactive categories | Every public query requires both to be active | "Customer listing leaves it out", "Customer listing is now empty" |
| 12 | 404 for missing products | `Product not found` | "Missing product", "PATCH a missing product", "Delete a missing product" |
| 13 | 400, 401, 403, 422 | See §3 | "Malformed JSON" (400), "Anonymous cannot create" (401), "Customer cannot…" (403), validation steps (422) |
| 14 | Clear duplicate-SKU error | 409 `A product with this SKU already exists`, also when the database detects it | `test_duplicate_found_only_by_the_database_is_409` |
| 15 | No internal database details | Fixed messages; driver errors are never passed on | `test_database_errors_reveal_no_internals` |

## 2. Endpoints and schemas

| Method | Path | Access | Request schema | Success |
|---|---|---|---|---|
| POST | `/api/products/` | ADMIN | `ProductCreate` | 201 `ProductResponse` |
| GET | `/api/products/` | Public | query parameters | 200 page of `ProductResponse` |
| GET | `/api/products/{product_id}` | Public | — | 200 `ProductResponse` |
| PUT | `/api/products/{product_id}` | ADMIN | `ProductReplace` (every field) | 200 `ProductResponse` |
| PATCH | `/api/products/{product_id}` | ADMIN | `ProductUpdate` (any fields) | 200 `ProductResponse` |
| DELETE | `/api/products/{product_id}` | ADMIN | — | 200 `{"message": "Product deactivated"}` |

`/api/products` without the slash also works, without a redirect.

| Schema | Fields |
|---|---|
| `ProductCreate` | `category_id`, `name`, `sku`, `price` required; `description`, `discount_price`, `image_url`, `brand`, `initial_stock` optional |
| `ProductReplace` | `category_id`, `name`, `description`, `sku`, `price`, `discount_price`, `image_url`, `brand`, `is_active`, all required; the four optional values may be `null` |
| `ProductUpdate` | Any of the `ProductReplace` fields, at least one; `category_id`, `name`, `sku`, `price` and `is_active` cannot be `null` |
| `ProductResponse` | All stored fields plus `effective_price` and `in_stock` |

Every request schema rejects unknown and read-only fields (`id`, `stock_quantity`, timestamps)
with 422.

## 3. Status codes

| Status | Meaning | Example message |
|---|---|---|
| 400 | Body is not a JSON object: malformed JSON, no body, an array, form data | `Request body is not valid JSON` |
| 401 | No valid token on a write or `include_inactive` | `Could not validate credentials` |
| 403 | Valid token, not ADMIN | `Admin role required` |
| 404 | Unknown product, or hidden from this caller | `Product not found` |
| 409 | Duplicate SKU | `A product with this SKU already exists` |
| 422 | Well-formed JSON with invalid fields, or an invalid ID/query | `{"field": "discount_price", "message": "discount_price must be lower than price"}` |
| 503 | Authentication Service or database unavailable | `Service temporarily unavailable` |

400 or 422: if the body cannot be read as a JSON object at all, the request is malformed (400).
If it is a JSON object whose fields break the rules, it is 422, with one entry per field.

## 4. Design decisions

| Decision | Reason |
|---|---|
| DELETE is a soft delete (deactivation) | Inventory transactions reference the product (foreign key RESTRICT), and orders in other ShopEase services refer to product IDs. Removing the row would break both. The product disappears from customers at once, and the change can be undone |
| Discount must be strictly lower than price | A discount equal to the price is not a discount. The database CHECK uses the same rule |
| A price of 0 is allowed | The requirement is to refuse negative prices; free items are valid. The database CHECK is `price >= 0` |
| Hidden products return 404, not 403 | Customers cannot tell an inactive product from one that never existed |
| Stock is never edited directly | Every change goes through an inventory transaction, so the history is complete |
| SKUs are stored upper-case | `abc-1` and `ABC-1` are the same SKU on every database, whatever its collation |

## 5. Issues found and fixed during this task

| Issue | Found by | Fix |
|---|---|---|
| A duplicate SKU detected by the database when `initial_stock` was set gave the vague `The request conflicts with existing data` instead of the duplicate-SKU message. The error was raised at the early flush, before the service's error handling | Race test with a skipped service check | The whole write, flush included, is now one guarded block (`_write`) |
| `"19.5"` was echoed back as `"19.5"` on create, while MySQL stores and returns `"19.50"` | Writing the tests | Prices are normalised to two places on input, so the response equals what is stored |
| Every integrity error was reported as a duplicate SKU | Code review | Only unique violations get that message; others get a generic conflict message |
| A category could be deactivated or deleted while a product was being saved into it | Code review | The category row is read with `FOR SHARE` until the transaction ends |
| A discount error was reported on the whole body (`"field": "body"`) | Writing the tests | It is now reported on `discount_price` |

## 6. How the evidence was produced

`python -m scripts.product_api_evidence` writes the transcript. Every step states the caller, the
request, the expected and actual status, and the full response.

- **Part A (42 steps): write scenarios.** The real application with the real MySQL 8.4 test
  database (`shopease_product_catalog_test_db`), inside one transaction that was rolled back
  afterwards. A check of the database after the run found none of the rows. Only the
  Authentication Service is a stand-in: the live one has no ADMIN account (see
  `02_JWT_Integration.md`), so ADMIN and customer tokens are answered the way its
  `verify-token` endpoint answers.
- **Part B (12 steps): live container.** The running service on port 8006, with its configured
  database and the **real** Authentication Service. Only reads and requests that must be refused
  were sent: public listing, 404, 422, 401 for each write without a token, a forged ADMIN token
  rejected by the real Authentication Service, and 400 for malformed JSON.

Not shown: a live write with a real ADMIN token. This needs an ADMIN account in the
Authentication Service, which can only be created by a direct change to its database.

## 7. Results

| Run | Result |
|---|---|
| `tests/test_product_api.py`, SQLite | 111 passed |
| `tests/test_product_api.py`, MySQL 8.4 test database | 111 passed |
| Whole suite, SQLite | 350 passed, 1 skipped (a MySQL-only test) |
| Whole suite, MySQL 8.4 test database | 351 passed |
| API transcript | 54 of 54 steps with the expected status |

Logs: `Test_Results/product_api_logs/01_pytest_product_api.log` and `02_api_transcript.md`.

## 8. Changes after this task

Task 8 (`04_Product_Search.md`) renamed the list parameters (`size`, `sort`, `order`, `in_stock`
became `page_size`, `sort_by`, `sort_order`, `availability`) and the page fields (`size`, `pages`
became `page_size`, `total_pages`). It moved the four list tests from `tests/test_product_api.py`
(now 107 tests) to `tests/test_product_search.py`. The Part B step "Bad query parameter" now sends
`page_size=1000` instead of `size=1000`, and the transcript was recorded again afterwards: 54 of
54 steps as expected. The pytest log `01_pytest_product_api.log` is the Task 7 run and is unchanged.
