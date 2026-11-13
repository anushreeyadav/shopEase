# Screenshot checklist (submission)

The 18 screenshots, in their folders under `DELIVERABELS/screenshots/submission/` (PNG).

**Status, 13 November 2026: all 18 captured** on this computer:
- Swagger UI items: `python -m scripts.take_submission_screenshots` sends real requests from Swagger UI in
  Microsoft Edge (`scripts/submission_screenshots.js`). Each image has a banner naming the instance, the token
  used and the time; every token is shown as `<token hidden>`.
- Terminal items (3, 16, 18): `scripts/capture_console_screenshots.ps1` opens a real console window, runs the
  command and captures the window.
- ADMIN items (4, 5, 8, 10–15) were taken on the **test instance** (option B below), because the live
  Authentication Service still has no ADMIN account; their file names end in `_test_instance`. Item 10 also has
  `customer_403_live.png`, taken on the live service with a real customer account.
- Item 1 (VS Code Explorer) was captured manually by the student in three screenshots, scrolled from top to
  bottom: `vscode_project_structure_1.png` … `_3.png` (the script could not open a separate VS Code window while
  VS Code was updating).
- All screenshots are collected in `ShopEase_Submission_Screenshots.pptx` in this folder.
- To retake the ADMIN items on the live service once an account has the ADMIN role, set `ADMIN_EMAIL` /
  `ADMIN_PASSWORD` (and `CUSTOMER_EMAIL` / `CUSTOMER_PASSWORD`) and run
  `python -m scripts.take_submission_screenshots` again (needs `NODE_PATH` pointing at a folder with
  `playwright-core`). It then uses the live service and writes the files without `_test_instance`.

Rules:
- Real screens only: no edited, mocked or sample images.
- Before saving, hide or crop any token, password or `.env` content. In Swagger UI the token appears in the
  generated **curl** command and in the **Authorize** dialog.
- Make the address bar or terminal prompt visible where possible, so the reader can see which service it is
  (`127.0.0.1:8006` is live; `127.0.0.1:8016` is the test instance).
- A **test-instance** screenshot (8016) must say so in its caption or file name (`..._test_instance.png`).

## Before you start

```powershell
cd C:\Users\Administrator\ShopEase\shopease-product-catalog-service
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d   # live stack: API 8006, MySQL 127.0.0.1:3310
docker compose ps                                                      # both "healthy"
```

**ADMIN screenshots (items 4, 5, 8, 10, 11–15).** The live Authentication Service has no ADMIN account, so
these operations cannot be done on the live service (8006) today. Two options:

| Option | How | Caption |
|---|---|---|
| A. Live (preferred) | The Authentication Service owner creates an ADMIN account. Log in at `POST http://127.0.0.1:8001/api/auth/login`, then in http://127.0.0.1:8006/docs click **Authorize** and paste the `access_token`. For the customer view, log in with a `USER` account | "live service" |
| B. Test instance | `.\.venv\Scripts\python.exe -m scripts.screenshot_test_instance` starts the test instance on http://127.0.0.1:8016/docs (MySQL test database, stand-in Authentication Service) and prints an ADMIN and a USER token. Press Enter when done: it deletes only the rows created in that session | "test instance, stand-in Authentication Service" |

## Checklist

| # | Folder / file | What must be visible | How | Live or test | Status |
|---|---|---|---|---|---|
| 1 | `01_vscode_project_structure/vscode_project_structure.png` | VS Code Explorer with `app/` (core, database, models, schemas, services, routers), `alembic/`, `tests/`, `postman/`, `scripts/`, `DELIVERABELS/`, Dockerfile, docker-compose files, README | Open the folder in VS Code and expand the top-level folders and `app/` | — | [x] Captured 13 Nov 2026 (manually): vscode_project_structure_1.png, _2.png, _3.png |
| 2 | `02_swagger_ui/swagger_ui.png` | http://127.0.0.1:8006/docs with the Categories, Products, Inventory and Service groups | Browser | Live | [x] Captured 13 Nov 2026: swagger_ui.png (live) |
| 3 | `03_mysql_database_and_tables/mysql_tables.png` | `shopease_product_catalog_db` with `alembic_version`, `categories`, `inventory_transactions`, `products` (and ideally `DESCRIBE products;`) | MySQL Workbench to `127.0.0.1:3310`, or `docker exec -it shopease-product-catalog-service-catalog-mysql-1 mysql -u <MYSQL_USER> -p shopease_product_catalog_db` then `SHOW TABLES;` `DESCRIBE products;` (type the password at the prompt; do not show it) | Live | [x] Captured 13 Nov 2026: mysql_tables.png, describe_products.png (live database) |
| 4 | `04_category_creation/category_created_201.png` | `POST /api/categories/` with body and **201** response | Swagger, Authorize as ADMIN, Try it out | A or B | [x] Captured 13 Nov 2026: category_created_201_test_instance.png |
| 5 | `05_product_creation/product_created_201.png` | `POST /api/products/` (with `initial_stock`) and **201** response | Swagger as ADMIN, using the new category's `id` | A or B | [x] Captured 13 Nov 2026: product_created_201_test_instance.png |
| 6 | `06_product_listing/product_listing_200.png` | `GET /api/products/` **200** with `items`, `total`, `page`, `page_size`, `total_pages` | Swagger (no token needed) | Live (empty list until products exist) or B | [x] Captured 13 Nov 2026: product_listing_200_test_instance.png |
| 7 | `07_product_search_and_filtering/search_filter_200.png` | `GET /api/products/` with e.g. `search`, `min_price`, `max_price`, `sort_by=price`, `sort_order=desc`, `page_size` and the **200** result | Swagger | Live or B | [x] Captured 13 Nov 2026: search_filter_200_test_instance.png |
| 8 | `08_product_update/product_update_200.png` | `PATCH /api/products/{id}` (e.g. new price) and **200** response showing the change | Swagger as ADMIN | A or B | [x] Captured 13 Nov 2026: product_update_200_test_instance.png |
| 9 | `09_jwt_authorization_failure/no_token_401.png` (+ optional `invalid_token_401.png`) | `POST /api/products/` without a token → **401** `Could not validate credentials`; optional: Authorize with `abc.def.ghi` → 401 | Swagger, logged out | Live | [x] Captured 13 Nov 2026: no_token_401.png, invalid_token_401.png (live) |
| 10 | `10_admin_vs_customer_access/admin_201.png` and `customer_403.png` | The same admin request (e.g. stock-in) as ADMIN → **201** and as a customer (`USER`) → **403** `Admin role required` | Swagger: Authorize with each token in turn (Logout between) | A or B | [x] Captured 13 Nov 2026: admin_201_test_instance.png, customer_403_test_instance.png, customer_403_live.png (real customer account) |
| 11 | `11_stock_in/stock_in_201.png` | `POST /api/inventory/{id}/stock-in` `{"quantity": 10, "remarks": "..."}` → **201**, `previous_stock` and `updated_stock` | Swagger as ADMIN | A or B | [x] Captured 13 Nov 2026: stock_in_201_test_instance.png |
| 12 | `12_stock_out/stock_out_201.png` | `POST /api/inventory/{id}/stock-out` → **201**, stock reduced | Swagger as ADMIN | A or B | [x] Captured 13 Nov 2026: stock_out_201_test_instance.png |
| 13 | `13_insufficient_stock_validation/insufficient_stock_409.png` | Stock-out larger than the stock → **409** `Insufficient stock: N available, M requested` | Swagger as ADMIN | A or B | [x] Captured 13 Nov 2026: insufficient_stock_409_test_instance.png |
| 14 | `14_inventory_history/history_200.png` | `GET /api/inventory/{id}/history` → **200**, IN and OUT rows newest first | Swagger as ADMIN | A or B | [x] Captured 13 Nov 2026: history_200_test_instance.png |
| 15 | `15_low_stock_products/low_stock_200.png` | `GET /api/inventory/low-stock` → **200** listing a product at or below 5 | Swagger as ADMIN (stock-out a product down to 5 or less first) | A or B | [x] Captured 13 Nov 2026: low_stock_200_test_instance.png |
| 16 | `16_docker_containers_running/docker_compose_ps.png` | `docker compose ps`: `catalog-service` and `catalog-mysql` **Up (healthy)**, port 8006 | Terminal in the project folder | Live | [x] Captured 13 Nov 2026: docker_compose_ps.png (live) |
| 17 | `17_health_check/health_200.png` | `GET http://127.0.0.1:8006/health` → `{"status":"ok",...}` (and `/health/db`) | Browser, Swagger, or `curl.exe http://127.0.0.1:8006/health` | Live | [x] Captured 13 Nov 2026: health_200.png, health_db_200.png (live) |
| 18 | `18_passing_automated_tests/pytest_passed.png` | The end of a pytest run: `525 passed, 6 skipped` (SQLite) or `531 passed` (MySQL) | `.\.venv\Scripts\python.exe -m pytest -q`; for MySQL first `$env:CATALOG_SERVICE_TEST_DB="mysql"; $env:MYSQL_DATABASE="shopease_product_catalog_test_db"` (remove both afterwards) | — | [x] Captured 13 Nov 2026: pytest_passed.png (525 passed, 6 skipped) |

## Already in this folder (supporting evidence, not a substitute)

The 14 PNG files directly in `DELIVERABELS/screenshots/` (`01_live_*` … `14_test_*`) were taken automatically in
Task 11 by `scripts/swagger_screenshots.js`. They show real requests sent from Swagger UI in Microsoft Edge,
with a banner naming the instance. Files 01–06 show the live service and 07–14 the test instance. They are
supporting evidence; the checklist above is for the screenshots you capture yourself.
