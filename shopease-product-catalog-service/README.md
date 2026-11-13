# ShopEase Product Catalog Service

FastAPI microservice for the ShopEase catalog: **categories**, **products** and **inventory**.
It uses its own MySQL database (`shopease_product_catalog_db`) and checks tokens with the
ShopEase Authentication Service. It holds no JWT secret.

| | |
|---|---|
| Version | 1.0.0 |
| Python | 3.11 |
| API port | **8006** (`SERVICE_PORT`) |
| MySQL port on this machine | **3310** (with `docker-compose.dev.yml`) |
| Swagger UI | http://127.0.0.1:8006/docs |

Ports 8000–8005 belong to the other ShopEase services (gateway, auth, user, product, order,
payment), and the service refuses to start on any of them.

## Configuration

All settings live in [app/core/config.py](app/core/config.py) and are read from environment
variables or `.env` (environment variables win). Copy `.env.example` to `.env` and replace every
`change-me` value; the service refuses to start with a placeholder password. `.env` is ignored by
Git and by Docker builds.

| Variable | Default | Purpose |
|---|---|---|
| `SERVICE_HOST` / `SERVICE_PORT` | `127.0.0.1` / `8006` | Address used by `python -m app` and Docker |
| `MYSQL_DATABASE` | `shopease_product_catalog_db` | Database name |
| `MYSQL_USER` / `MYSQL_PASSWORD` | none (required) | Database credentials |
| `MYSQL_HOST` / `MYSQL_PORT` | `127.0.0.1` / `3310` | Database address |
| `AUTH_SERVICE_VERIFY_URL` | `http://127.0.0.1:8001/api/auth/verify-token` | Token verification endpoint |
| `AUTH_SERVICE_TIMEOUT_SECONDS` | `5` | Timeout for that call |
| `JWT_ALGORITHM` | `HS256` | Must match the Authentication Service (HS256/HS384/HS512) |
| `LOW_STOCK_THRESHOLD` | `5` | Stock at or below this is reported as low |
| `APP_ENV`, `LOG_LEVEL`, `API_PREFIX`, `DOCS_ENABLED` | `development`, `INFO`, `/api`, `true` | Application |

### How tokens are verified

The Authentication Service (`shopease-auth-service`) signs tokens with HS256 and a shared secret,
with the claims `sub`, `role`, `iat` and `exp`. This service:

1. Rejects locally anything that is not a well-formed JWT whose header names `JWT_ALGORITHM`
   (python-jose, no secret involved). This only saves a network call and never accepts a token.
2. Sends the token to `POST /api/auth/verify-token`. Only a 200 response authenticates the caller.
   That endpoint also rejects deleted or deactivated users and returns the current role.

The signing secret stays in the Authentication Service. Holding it here would let this service
create tokens, including admin tokens.

If the Authentication Service is down, slow (over `AUTH_SERVICE_TIMEOUT_SECONDS`) or answers with
an error, requests with a token get **503** and are refused (fail closed). Anonymous browsing does
not call it and keeps working. Full details: `DELIVERABELS/02_JWT_Integration.md`.

## Access rules

The Authentication Service has two roles: `USER`, the default for every registered account (the
shop's customers), and `ADMIN`. It has no `CUSTOMER` role. Roles are matched exactly, and the role
used is the one `verify-token` returns from its database, not the token's claim.

| Who | Can do |
|---|---|
| Anyone, including customers (`USER`) | Browse active categories and products, which include `stock_quantity` and `in_stock` |
| `ADMIN` role | Create, update and deactivate categories and products; every `/api/inventory` route; `include_inactive=true` |

| Status | When |
|---|---|
| 401 | No token, wrong scheme, malformed, expired or wrongly signed token, unknown user. Also for an invalid token on public routes |
| 403 | Valid token, but the user is inactive or the role is not allowed |
| 503 | The Authentication Service could not verify the token |

Dependencies for new routes, in `app/core/security.py`: `get_current_authenticated_user`,
`get_optional_user`, `require_admin`, and `require_roles("ADMIN", ...)`.

Live check against the running Authentication Service (read-only):
`python -m scripts.auth_integration_check`. Set `CHECK_CUSTOMER_EMAIL`/`CHECK_CUSTOMER_PASSWORD`
and `CHECK_ADMIN_EMAIL`/`CHECK_ADMIN_PASSWORD` to include real logins.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/health`, `/health/db` | Service and database health |
| GET | `/api/categories/` | Public, active only. `include_inactive=true` with an admin token |
| GET | `/api/categories/{id}` | Public. Inactive categories are 404, except admin with `include_inactive=true` |
| POST | `/api/categories/` | Admin. 201. `name` required, `description` optional |
| PUT | `/api/categories/{id}` | Admin. Replaces `name`, `description` (null clears) and `is_active`; all required |
| PATCH | `/api/categories/{id}` | Admin. Changes only the fields sent, for example `{"is_active": false}` |
| DELETE | `/api/categories/{id}` | Admin. Only categories with no products (409 otherwise, see below) |
| GET | `/api/products/` | Public, active products in active categories. Search, filters, paging and sorting: see [below](#product-search-filters-paging-and-sorting) |
| GET | `/api/products/{id}` | Public. Missing, inactive, or in an inactive category: 404 (admin: `include_inactive=true`) |
| POST | `/api/products/` | Admin. 201. `initial_stock` is recorded as the first IN transaction |
| PUT | `/api/products/{id}` | Admin. Replaces every editable field; all required |
| PATCH | `/api/products/{id}` | Admin. Changes only the fields sent |
| DELETE | `/api/products/{id}` | Admin. Deactivates (soft delete); reactivate with PUT/PATCH `is_active: true` |
| GET | `/api/inventory/{product_id}` | Admin. Current stock and low-stock flag (see [Inventory](#inventory)) |
| GET | `/api/inventory/low-stock` | Admin. Active products at or below `LOW_STOCK_THRESHOLD` |
| POST | `/api/inventory/{product_id}/stock-in` · `/stock-out` | Admin. `{"quantity": n, "remarks": "..."}` |
| GET | `/api/inventory/{product_id}/history` | Admin. Complete stock history, newest first; `page`, `page_size`, `transaction_type` |

The category and product collections answer at both `/api/categories/` and `/api/categories`
(and `/api/products/`, `/api/products`), without a redirect.

### Categories

| Rule | Behaviour |
|---|---|
| Name | Required. Surrounding spaces removed, inner runs of spaces become one. 1–100 characters, at least one letter or digit, no control characters (including tabs and line breaks) |
| Unique name | Letter case is ignored (`Footwear` = `FOOTWEAR`): 409 `A category with this name already exists`. On MySQL, accents are ignored too (`Café` = `Cafe`) |
| Description | Optional, up to 5000 characters; line breaks allowed. `null` clears it |
| Activation | `is_active: false` (PUT or PATCH) hides the category **and its products** from public listings; `true` shows them again |
| Visibility | Visitors and customers (`USER`) see only active categories. Admins see inactive ones with `include_inactive=true` |
| Delete policy | A category that contains any product, active or inactive, is not deleted: 409 `Category still contains N products ...`, and nothing changes. Products are never moved or deleted automatically. To retire it, deactivate it, or move its products (`PATCH /api/products/{id}` with a new `category_id`) and then delete it |
| Transactions | Each write is one transaction, rolled back on any error. If two requests race, the database's unique constraint and foreign key (RESTRICT) still decide, and the loser gets the same 409 |

| Status | When |
|---|---|
| 200 / 201 | Read, update, delete / create |
| 401 | Write without a valid token; `include_inactive` without a token |
| 403 | Write or `include_inactive` by a non-admin |
| 404 | Unknown ID, or inactive category for a non-admin |
| 409 | Duplicate name, or delete of a category that has products |
| 400 | Body is not a JSON object (malformed JSON, missing, array, form data) |
| 422 | Invalid fields or ID (`0`, `-1`, `abc`, too large). The body lists each field: `{"detail": "Validation failed", "errors": [{"field": "name", "message": "..."}]}` |

### Products

| Rule | Behaviour |
|---|---|
| Required on create | `category_id`, `name`, `sku`, `price`. Optional: `description`, `discount_price`, `image_url`, `brand`, `initial_stock` |
| Category | Must exist and be active, on create and when `category_id` changes (422 on `category_id`) |
| Name, brand | Spaces trimmed and collapsed; at least one letter or digit; no control characters. Name up to 200 characters |
| SKU | Letters, digits and hyphens, starting with a letter or digit, up to 64. Stored upper-case. Unique, ignoring case: 409 `A product with this SKU already exists` |
| Money | `Decimal`, never float. Send as a string (`"19.99"`) or a number. 0 to 99,999,999.99, at most 2 decimal places; negative values are refused. Returned as strings with exactly two places (`"19.5"` is stored and returned as `"19.50"`) |
| Discount | `discount_price` must be **lower** than `price` (equal is not a discount). When only one of them is sent in a PATCH, it is checked against the stored value of the other. `effective_price` = discount when set, else price |
| Stock | Never negative. `stock_quantity` is not accepted by POST, PUT or PATCH (422); it changes only through `/api/inventory`. `initial_stock` (0 to 1,000,000,000) becomes the first IN transaction |
| PUT / PATCH | PUT needs every editable field (`null` clears `description`, `discount_price`, `image_url`, `brand`). PATCH needs at least one field; required fields cannot be `null` |
| Delete | Soft delete: `is_active` becomes false and the row stays, because its inventory history and other services' orders refer to it. Repeating it is harmless |
| Visibility | Visitors and customers see only active products in active categories; anything else is 404, the same as a missing product. Admins use `include_inactive=true` |
| Transactions | Each write, including a new product's initial-stock transaction, is one transaction rolled back on any error. The category row is locked while a product is saved, so it cannot be deactivated or deleted halfway. A database refusal gets a fixed message with no SQL, constraint names or values |

| Status | When |
|---|---|
| 200 / 201 | Read, update, delete / create |
| 400 | Body is not a JSON object: malformed JSON, no body, an array, or form data. `{"detail": "Request body is not valid JSON"}` |
| 401 | Write or `include_inactive` without a valid token |
| 403 | Write or `include_inactive` by a non-admin |
| 404 | Unknown product, or hidden from this caller |
| 409 | Duplicate SKU |
| 422 | A JSON object with invalid fields, or an invalid ID or query parameter. Lists each field and the reason |

### Product search, filters, paging and sorting

`GET /api/products/` takes these query parameters, all optional. Filters combine with AND.

| Parameter | Values | Meaning |
|---|---|---|
| `search` | 1–100 characters | Part of the product name **or** SKU, ignoring case. Surrounding spaces are ignored; `%` and `_` match themselves |
| `category_id` | positive integer | Only products in this category. An unknown or inactive category gives an empty list |
| `min_price` | decimal ≥ 0, 2 places | Price at least this (inclusive) |
| `max_price` | decimal ≥ 0, 2 places | Price at most this (inclusive); must not be below `min_price` |
| `availability` | `in_stock`, `out_of_stock` | Stock above 0, or stock 0. Leave out for both |
| `brand` | 1–100 characters | Exact brand, ignoring case |
| `page` | 1–100000, default 1 | Page number |
| `page_size` | 1–100, default 20 | Items per page |
| `sort_by` | `name` (default), `price`, `created_at` | Sort column; no other column is accepted |
| `sort_order` | `asc` (default), `desc` | Direction |
| `include_inactive` | `true`, `false` | Admin only: also inactive products and products in inactive categories |

Examples:

```
GET /api/products/?search=mobile
GET /api/products/?category_id=1
GET /api/products/?min_price=1000&max_price=5000
GET /api/products/?page=1&page_size=10
GET /api/products/?sort_by=price&sort_order=asc
GET /api/products/?search=phone&availability=in_stock&sort_by=price&sort_order=desc&page=2&page_size=5
```

Response:

```json
{"items": [ ... ], "total": 23, "page": 2, "page_size": 5, "total_pages": 5}
```

| Rule | Behaviour |
|---|---|
| Visibility | Visitors and customers get only active products in active categories, whatever the filters; `total` counts only those. A hidden product cannot be found by its SKU either |
| Price | The filters and `sort_by=price` use the normal `price`, not `discount_price` |
| Sorting | Ties (same name, price or creation second) are ordered by ID in the same direction, so paging never repeats or skips a product |
| Pages | `total_pages` = `total` ÷ `page_size`, rounded up; 0 when nothing matches. A page past the last one returns `items: []` with the correct `total` (200, not an error) |
| Validation | 422 with the field and reason for page 0 or negative, `page_size` 0 or above 100, any other `sort_by` / `sort_order` / `availability` value, a negative or non-numeric price, more than 2 decimal places, `max_price` below `min_price`, and unknown parameters (for example `size`: `Unknown query parameter`) |
| Database | Filters, the count, sorting and paging all run in MySQL: one `COUNT` query and one query for the requested page (`ORDER BY ... LIMIT ... OFFSET`). Products are never loaded into memory to be filtered. Indexes: `price`, `created_at`, `name`, `category_id`, unique `sku` |

The inventory history (`GET /api/inventory/{product_id}/history`) pages the same way, with
`page`, `page_size` and the same response fields.

### Inventory

Every inventory endpoint needs an ADMIN token (401 without a valid token, 403 for customers).

| Endpoint | Success | Errors |
|---|---|---|
| `GET /api/inventory/{product_id}` | 200 `{product_id, sku, name, stock_quantity, low_stock_threshold, is_low_stock}` | 404, 422 invalid ID |
| `POST /api/inventory/{product_id}/stock-in` | 201 `{transaction, stock}` | 404, 409 above 1,000,000,000, 422, 400 |
| `POST /api/inventory/{product_id}/stock-out` | 201 `{transaction, stock}` | 404, 409 `Insufficient stock: N available, M requested`, 422, 400 |
| `GET /api/inventory/{product_id}/history` | 200 page of transactions, newest first | 404, 422 |
| `GET /api/inventory/low-stock` | 200 list, lowest stock first | — |

Request body for both movements: `{"quantity": 20, "remarks": "Delivery from supplier"}`.
`quantity` must be a JSON whole number from 1 to 1,000,000,000: `0`, negative numbers, `1.5`,
`5.0`, `"5"`, `true` and `null` are refused with 422. `remarks` is optional, one line, up to 255
characters.

Each transaction records `transaction_type` (IN or OUT), `quantity`, `previous_stock`,
`updated_stock`, `remarks` and `created_at` (UTC).

**Workflow of one stock movement** (`app/services/inventory_service.py`), all in one database
transaction:

1. `SELECT ... FROM products WHERE id = ? FOR UPDATE` locks the product row. A simultaneous
   movement of the same product waits until this one ends, then reads the new stock. Other
   products are not blocked. Unknown product: 404.
2. The new stock is calculated from the locked, current value. A stock-out that would go below 0
   is refused with 409 and nothing is written.
3. `products.stock_quantity` is updated and an `inventory_transactions` row is inserted.
4. `COMMIT` saves both. If anything fails (the update, the insert, the commit itself, or the
   connection) the transaction is rolled back: neither change is kept and the lock is released.
   A lost database answers 503; a database refusal answers 409.

**Initial stock:** `initial_stock` on `POST /api/products/` creates the product with stock 0 and
then records an IN transaction (`previous_stock` 0, remarks `Initial stock`), in the same
transaction as the product itself. With no `initial_stock` (or 0) there is no transaction. If
the product is refused (for example a duplicate SKU), no transaction is kept either.

**Stock never changes silently:** product requests (POST, PUT, PATCH) refuse `stock_quantity`
with 422. In addition, `app/models/stock_guard.py` checks every database write made by the
application: a change to `stock_quantity` without matching transaction rows, or a new product
that does not start at 0, is refused and rolled back. A manual SQL `UPDATE` run directly on the
database bypasses this, so stock corrections must also go through stock-in or stock-out.

**Low stock:** `LOW_STOCK_THRESHOLD` (environment or `.env`, default 5, 0 to 1,000,000,000).
Active products with stock **at or below** it are listed. Inactive products are left out, though
their stock and history can still be read and changed.

**History:** every transaction of the product, including its initial stock, newest first.
`total` is the number of transactions, and the pages (`page_size` up to 100) together return all
of them. Optional `transaction_type=IN` or `OUT`. Transactions are never changed or deleted, and
a product with history cannot be deleted (foreign key RESTRICT; DELETE deactivates instead).

**Consistency:** the database also enforces it, with CHECK constraints: `stock_quantity >= 0`,
`quantity > 0`, and `updated_stock = previous_stock ± quantity`. Replaying a product's history
from 0 always gives its current stock.

## Database

MySQL 8 database `shopease_product_catalog_db`, created only by Alembic
(`alembic/versions/`).

| Table | Columns | Constraints and indexes |
|---|---|---|
| `categories` | id, name, description, is_active, created_at, updated_at | name unique and not blank |
| `products` | id, category_id, name, description, sku, price, discount_price, stock_quantity, image_url, brand, is_active, created_at, updated_at | sku unique; FK category_id (RESTRICT); price ≥ 0; 0 ≤ discount_price < price; stock_quantity ≥ 0; indexes on name, category_id, price, created_at |
| `inventory_transactions` | id, product_id, transaction_type, quantity, previous_stock, updated_stock, remarks, created_at | FK product_id (RESTRICT); type IN/OUT; quantity > 0; updated = previous ± quantity; index (product_id, created_at) |

Money columns are `DECIMAL(10, 2)` (Python `Decimal`). Timestamps are stored as UTC and returned
with an explicit offset; the app sets each MySQL session to UTC. CHECK constraints need MySQL 8.0.16+.

## Database migrations

Alembic owns the schema; tables are never created by hand or by `create_all()`.

- `alembic.ini` holds no database URL or credentials. `alembic/env.py` builds the URL from the
  same settings as the app (`MYSQL_*` in `.env` or the environment) and imports every model
  through `app.models`, so autogenerate sees all three tables.
- `env.py` refuses any database other than `shopease_product_catalog_db` and the throwaway
  `shopease_product_catalog_test_db`.
- Migrations live in `alembic/versions/`: `5b8e2f0c9d14` creates the catalog tables, and
  `c4a7d2e91b30` adds the product listing indexes on `price` and `created_at`.

Run from the project root with the virtual environment active and MySQL reachable
(`docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d catalog-mysql`):

```powershell
alembic current                 # which revision the database is at (blank = not migrated)
alembic history --verbose       # all migrations
alembic upgrade head            # apply every pending migration
alembic check                   # fails if the models and the database differ
python -m scripts.migration_check --verify-only   # read-only check of tables, keys, indexes, CHECKs
```

The Docker image runs `alembic upgrade head` on every start, before the API opens its port.

**Changing the schema:** edit the model, then

```powershell
alembic revision --autogenerate -m "add products.weight"   # review the generated file before committing
alembic upgrade head
```

Autogenerate writes custom column types as `app.database.types.UTCDateTime()`; replace them with
`sa.DateTime()` so migrations do not depend on application code (see the initial migration).

**Testing downgrades — only on the test database.** `alembic downgrade` drops tables and their
data, so never run it against `shopease_product_catalog_db`. The full cycle (upgrade, downgrade to
empty, upgrade again, then probes that MySQL really enforces each constraint) runs only on the
test database and refuses any other:

```powershell
$env:MYSQL_DATABASE = "shopease_product_catalog_test_db"
python -m scripts.migration_check
$env:CATALOG_SERVICE_TEST_DB = "mysql"; pytest    # whole test suite on MySQL; changes are rolled back
Remove-Item Env:MYSQL_DATABASE, Env:CATALOG_SERVICE_TEST_DB
```

**First-time setup on an existing MySQL volume.** MySQL creates `MYSQL_DATABASE` only when its
volume is first initialised. If the volume already exists, create the databases instead of
deleting the volume (that would destroy whatever it holds):

```powershell
docker exec -it shopease-product-catalog-service-catalog-mysql-1 mysql -uroot -p
```
```sql
CREATE DATABASE IF NOT EXISTS shopease_product_catalog_db CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS shopease_product_catalog_test_db CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
GRANT ALL PRIVILEGES ON shopease_product_catalog_db.* TO 'catalog_svc'@'%';
GRANT ALL PRIVILEGES ON shopease_product_catalog_test_db.* TO 'catalog_svc'@'%';
```

The latest execution report is in `DELIVERABELS/Test_Results/Migration_Execution_Report.md`.

## Run with Docker

```powershell
Copy-Item .env.example .env      # then replace every change-me value
docker compose up --build -d     # MySQL 8.4 + API; the API waits for MySQL, runs "alembic upgrade head", then starts
docker compose ps                # both "Up ... (healthy)"
docker compose logs -f catalog-service
docker compose down              # keeps the database volume; never add -v (it deletes every database in it)
```

| Item | Setting |
|---|---|
| Services | `catalog-service` (API, `127.0.0.1:8006`), `catalog-mysql` (MySQL 8.4, not published) |
| Database | Always `shopease_product_catalog_db`; credentials from `.env` (required) |
| Data | Named volume `catalog_mysql_data`, kept by `docker compose down` |
| Start order | MySQL health check (the service user can open the database) → API container waits for the database (`python -m app.database.wait`) → `alembic upgrade head` → server |
| Database address | `catalog-mysql:3306` (Compose service name) |
| Auth Service | `http://host.docker.internal:8001/api/auth/verify-token` (the port it publishes on this machine). Optional shared network: `docker-compose.auth-network.yml` |
| Image | `python:3.11-slim-bookworm`, non-root user, only `app/`, `alembic/` and requirements copied; no `.env` or secret |

Options:

```powershell
# MySQL on 127.0.0.1:3310 for Alembic, pytest with MySQL, or the seed script:
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
# Auth Service over its Docker network (auth-service:8001) instead of host.docker.internal:
docker compose -f docker-compose.yml -f docker-compose.auth-network.yml up -d --build
```

Instructions and recorded evidence: `DELIVERABELS/Docker_Evidence/README.md`.

## Run locally (Python 3.11)

```powershell
py -3.11 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
python -m app                        # SERVICE_HOST:SERVICE_PORT, default 127.0.0.1:8006
python -m scripts.seed_sample_data   # optional sample categories and products
```

## Tests

```powershell
pytest                                          # SQLite in memory, no services needed
$env:CATALOG_SERVICE_TEST_DB="mysql"; pytest    # against shopease_product_catalog_db (migrated)
```

Each test runs in a transaction that is rolled back, so the MySQL run leaves no data behind.
The Authentication Service is replaced by a stand-in, so it does not need to be running.
`tests/test_config.py` covers every setting, the `.env.example` file and the ignore files.

## Postman

`python postman/gen_collection.py` writes the collection (the 20 mandatory test scenarios, a test
on every request) and an environment template without secrets into `postman/`. Import both, set
`admin_token` and `customer_token` to access tokens of an `ADMIN` and a `USER` account from the
Authentication Service (`POST http://127.0.0.1:8001/api/auth/login`), and run the folders in order.

`python -m scripts.run_postman_suite --newman <newman>` runs it with Newman: all scenarios on a
test instance (test database, stand-in Authentication Service), then the token-free folders on
the live service. Results and the full test report: `DELIVERABELS/Test_Results/Task11_API_Test_Report.md`.

## Submission deliverables and final audit

```powershell
python -m scripts.final_audit                 # read-only audit: endpoints, migration, JWT, Docker, secrets, .env
pip install python-docx                       # documentation tool only, not a service dependency
python -m scripts.build_word_documents        # the nine Word documents, figures read from the evidence files
python -m scripts.screenshot_test_instance    # test instance + ADMIN/USER tokens for manual screenshots
python -m scripts.take_submission_screenshots # Swagger UI submission screenshots (real requests, tokens hidden)
powershell -ExecutionPolicy Bypass -File scripts\capture_console_screenshots.ps1   # terminal screenshots
python -m scripts.live_customer_check         # live: a real customer token gets 403 on every ADMIN route
pip install pytest-cov; python -m pytest --cov=app   # optional line coverage (not a service dependency)
```

The screenshot and live-check scripts take credentials only from environment variables (`CUSTOMER_EMAIL`,
`CUSTOMER_PASSWORD`, optional `ADMIN_EMAIL`, `ADMIN_PASSWORD`); see each script's docstring. Without a live ADMIN
account the ADMIN screenshots are taken on the test instance and named `..._test_instance.png`.

| Deliverable | Location |
|---|---|
| Word documents (9) | `DELIVERABELS/Word_Documents/` |
| Final completion checklist | `DELIVERABELS/Final_Completion_Checklist.md` |
| API endpoint reference, OpenAPI | `DELIVERABELS/API_Documentation/` |
| Schema SQL reference (reference only; Alembic creates the tables) | `DELIVERABELS/Database_Evidence/schema_reference.sql` |
| Test execution summary, final audit | `DELIVERABELS/Test_Results/Test_Execution_Summary.md`, `Test_Results/final_audit/` |
| Postman collection and environment template | `postman/` |
| Submission screenshots and checklist | `DELIVERABELS/screenshots/submission/`, `DELIVERABELS/screenshots/SCREENSHOT_CHECKLIST.md` |
| Live customer check, line coverage | `DELIVERABELS/Test_Results/live_customer/`, `Test_Results/final_audit/04_coverage_mysql.txt` |
| Teams daily update templates | `DELIVERABELS/Progress_Reports/` |

## Layout

```
app/
  main.py            app, routers, error handlers, health endpoints
  __main__.py        "python -m app": starts Uvicorn with SERVICE_HOST / SERVICE_PORT
  core/              config.py (settings), security.py (token checks via the Auth Service)
  database/          base.py (Base, timestamp columns), types.py (UTCDateTime),
                     connection.py (engine, get_db, session_scope)
  models/            Category, Product, InventoryTransaction ORM models
  schemas/           request/response models (+ common_schema.py)
  services/          business logic (+ errors.py: NotFound/Conflict/InvalidField)
  routers/           HTTP layer (+ responses.py: documented error responses)
alembic/             migrations (5b8e2f0c9d14: create catalog tables; c4a7d2e91b30: listing indexes)
tests/               pytest suite
postman/             collection generator
scripts/             seed_sample_data.py, migration_check.py, auth_integration_check.py,
                     product_api_evidence.py, product_search_evidence.py, inventory_evidence.py
                     (evidence transcripts), inventory_mutation_check.py, docker_secret_scan.py,
                     run_postman_suite.py, stand_in_auth_service.py, swagger_screenshots.js (Task 11),
                     final_audit.py, build_word_documents.py + docx_kit.py, screenshot_test_instance.py,
                     take_submission_screenshots.py + submission_screenshots.js, capture_console_screenshots.ps1,
                     live_customer_check.py (Task 12)
DELIVERABELS/        reports, screenshots and evidence
```
