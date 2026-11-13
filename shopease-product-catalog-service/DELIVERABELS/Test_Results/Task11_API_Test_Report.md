# Product Catalog API: Complete Test Report

| | |
|---|---|
| Task | 11: complete API testing with pytest, Swagger UI and Postman |
| Date | 12 November 2026 (times in the reports are UTC) |
| Service | ShopEase Product Catalog Service 1.0.0, migration `c4a7d2e91b30` |
| Result | **No test failed.** Some scenarios could not be run against the live Authentication Service; see §2 |

## 1. Summary

| Run | Where | Result |
|---|---|---|
| pytest, whole suite | SQLite in memory | **525 passed, 6 skipped** (the 6 need MySQL) |
| pytest, whole suite | MySQL 8.4 test database | **531 passed** |
| pytest, `tests/test_mandatory_scenarios.py` (the 20 scenarios and the cross-cutting checks) | both | 30 tests (23 functions), all passed on MySQL; 29 passed + 1 skipped (scenario 20) on SQLite |
| Postman / Newman, run A: scenarios 00–20a | Test instance, stand-in Authentication Service | **98 requests, 308 assertions, 0 failed** |
| Postman / Newman, run A: 20b, 12 Newman processes at once | same | 5 × 201, 7 × 409 (stock 5), 0 assertions failed |
| Postman / Newman, run A: 20c consistency, 99 cleanup | same | 5 requests, 13 assertions, 0 failed |
| Database verification after run A (direct SQL) | MySQL test database | **11 of 11 checks passed** |
| Postman / Newman, run B: folders 06, 19, L | **Live container, real Authentication Service** | **30 requests, 110 assertions, 0 failed** |
| Swagger UI, requests sent from the browser | Live (6) and test instance (8) | **14 screenshots**; each response had the expected status |
| Docker | Running stack | Both containers healthy; `/health`, `/health/db`, `/docs` 200 inside the container |

## 2. What could not be run live, and why

> **Update, 13 November 2026.** A customer account was registered through the Authentication Service's own
> API and scenario 18 was run live with its real token: 17 checks passed, 0 failed
> (`live_customer/live_customer_check.txt`). Line coverage is now measured: 96 % of `app/`
> (`final_audit/04_coverage_mysql.txt`). The ADMIN role is still not granted, so the ADMIN scenarios remain
> blocked live. The text below is the Task 11 record as written on 12 November.

The live Authentication Service (`shopease-auth-service`) has **14 active `USER` accounts and no
`ADMIN` account**. An ADMIN can only be created by a direct change to its database, and I have
no password for any of the USER accounts. I did not create or change any account.

The 20 scenarios were therefore run in two ways:

- **Run A (all 20 scenarios).**
  - The same application code, as a second instance (`python -m app`, port 8016), on the MySQL test
    database `shopease_product_catalog_test_db`.
  - Tokens are checked over HTTP by a **stand-in** for `POST /api/auth/verify-token`
    (`scripts/stand_in_auth_service.py`, port 8099). It applies the real service's rules: HS256
    signature, required claims, user lookup, inactive users.
  - Every row the run created was deleted afterwards. The test database holds 0 rows
    (`docker_execution_check.txt`).
- **Run B (live).** The running container on port 8006, with its configured database and the
  **real** Authentication Service. Only requests that need no valid token can be sent there:
  - scenario 6;
  - scenario 19 (no token, malformed token, forged token: the real Authentication Service
    rejects it);
  - public reads.

| Scenarios | Live status | Reason |
|---|---|---|
| 1–4, 7–10, 13–17, 20 | **Blocked live**; passed in run A and in pytest | Need an ADMIN token |
| 18 | **Blocked live**; passed in run A and in pytest | Needs a USER (customer) token |
| 5, 11, 12 | **Partly live**: listing, search, filters, paging and sorting answer correctly but return empty lists | The live database `shopease_product_catalog_db` holds no products; filling it needs an ADMIN |
| 6, 19 | **Passed live** | — |

To run everything live, create one ADMIN account in the Authentication Service and log in with it
and with a USER account. Then put both tokens in the Postman environment (`base_url`
`http://127.0.0.1:8006`) and run the collection. The collection needs no other change.

## 3. The 20 scenarios

Columns:
- **pytest:** a test in `tests/test_mandatory_scenarios.py`.
- **Run A / Run B:** Postman folder results.
- **Screenshot:** a file in `DELIVERABELS/screenshots/`.

| # | Scenario | pytest | Run A | Run B (live) | Screenshot |
|---|---|---|---|---|---|
| 1 | Create a product with valid information | `test_s01_…` PASS (row, FK and initial IN transaction checked in the database) | PASS: 201, SKU upper-case, `"1499.50"`, stock 7; history has 1 IN 7 | Blocked | 08 (201) |
| 2 | Duplicate SKU | `test_s02_…` PASS (exactly 1 row with that SKU) | PASS: 409 for the same SKU and for other letter case | Blocked | 09 (409) |
| 3 | Invalid category | `test_s03_…` PASS (no row created) | PASS: 422 for missing, inactive and non-numeric category | Blocked | — |
| 4 | Negative price | `test_s04_…` PASS, 3 cases (no row created) | PASS: 422 on `price` and on `discount_price` | Blocked | — |
| 5 | Retrieve all active products | `test_s05_…` PASS (inactive product and inactive category hidden for anonymous, customer and admin) | PASS | Partly: 200, only active products, empty | 03 (live, empty), 10 (test, with data) |
| 6 | Invalid product ID | `test_s06_…` PASS, 6 cases | PASS: 422 for `abc`, `0`, 2³¹; 404 for 999999 | **PASS** | 05 (live 404) |
| 7 | Update a product (PUT) | `test_s07_…` PASS (row checked; stock unchanged) | PASS: 200; 422 without every field; 404 missing | Blocked | — |
| 8 | Partially update a product (PATCH) | `test_s08_…` PASS | PASS: 200, other fields kept; `stock_quantity` 422; discount not below price 422 | Blocked | — |
| 9 | Delete / deactivate | `test_s09_…` PASS (row and history kept, `is_active` false) | PASS: 200; customers 404; admin sees it inactive; history kept | Blocked | — |
| 10 | Duplicate category | `test_s10_…` PASS (1 row) | PASS: 409 for other case and extra spaces | Blocked | — |
| 11 | Search and filter | `test_s11_…` PASS | PASS: name, SKU, category, price range, availability, combined; exact SKUs | Partly (empty) | 10 |
| 12 | Pagination and sorting | `test_s12_…` PASS | PASS: page fields, both pages, price asc/desc, name, past the end, 422s | Partly (empty) | 03, 10 |
| 13 | Increase stock | `test_s13_…` PASS (row and history) | PASS: IN 5, 7 → 12 | Blocked | 11 (201) |
| 14 | Decrease stock | `test_s14_…` PASS | PASS: OUT 4, 12 → 8 | Blocked | — |
| 15 | Reduce stock below zero | `test_s15_…` PASS (also: the database CHECK refuses −1 directly) | PASS: 409 `Insufficient stock: 8 available, 9 requested`, stock still 8; 0 and −1 → 422 | Blocked | 12 (409) |
| 16 | Transaction history | `test_s16_…` PASS (API ids = database rows; replay) | PASS: 3 rows newest first, all fields, replays without a gap | Blocked | 13 (200) |
| 17 | Low-stock products | `test_s17_…` PASS (5 listed, 6 not; lowest first) | PASS: this run's products at 0 and 4 listed, 7 and 12 not | Blocked | 14 (200) |
| 18 | Admin APIs as a CUSTOMER | `test_s18_…` PASS: 13 admin calls → 403; nothing changed | PASS: 8 calls → 403 `Admin role required`; customer can view; stock unchanged | Blocked | — |
| 19 | No JWT / invalid JWT | `test_s19_…` PASS: 5 token cases × 6 endpoints → 401 with `WWW-Authenticate: Bearer` | PASS: 21 requests → 401 | **PASS** (21 requests; the forged token is rejected by the real Authentication Service) | 04 (live 401) |
| 20 | Simultaneous stock updates | `test_s20_…` PASS on MySQL: 12 threads released together, stock 5 → exactly 5 succeed, history one chain | PASS: 12 Newman processes → 5 × 201, 7 × 409; stock 0; 6 history rows; replays | Blocked | — |

**About scenario 20 in Postman.** Each Newman process needs about a second to start, so the 12
requests began within about 4 seconds of each other (`postman/A2_burst/timeline.txt`). The
first ones overlapped: they took 450–990 ms, waiting on the row lock. The strict simultaneous
test is the pytest one, where the threads are released at the same moment by a barrier.
`tests/test_inventory_concurrency.py` adds three more variants. Removing the row lock makes all of
them fail (Task 9, `inventory_logs/03_mutation_checks.log`).

## 4. Also verified

| Item | How | Result |
|---|---|---|
| HTTP status codes | Every Postman request asserts its status and, for errors, the exact message; pytest likewise | 400/401/403/404/409/422/503 all as documented |
| Database records | Run A: direct SQL after the run (`postman/A6_database_verification.md`); pytest: rows read back after each scenario | Exactly the 8 expected products; refused requests created nothing; stock and history rows as expected |
| Foreign keys | SQL: every product's category exists, no orphan transactions, both FKs `ON DELETE RESTRICT` (information_schema); pytest `test_foreign_keys_are_enforced`: the database refuses deleting a referenced category or product and inserting an orphan transaction | PASS |
| SKU and category uniqueness | SQL over the whole test database (case-insensitive); pytest `test_uniqueness_is_enforced_by_the_database` (raw INSERTs refused); scenarios 2 and 10 | PASS |
| Stock constraints | No negative stock anywhere; CHECK constraints present; raw `UPDATE … stock_quantity = -1` refused (scenario 15); every product's stock equals its replayed history | PASS |
| JWT authorization | Scenarios 18 and 19 (pytest, run A, and live for 19); `tests/test_auth_integration.py` (35 tests: expired, tampered role, inactive user, Auth Service down → 503) | PASS |
| Transaction rollback | pytest `test_failed_stock_change_is_rolled_back` and `tests/test_inventory_api.py` (failure injected on the UPDATE, the INSERT and the COMMIT); Task 9 transcript | PASS. A rollback cannot be triggered through the public API without injecting a fault, so it is not part of the Postman collection |
| No internal details in responses | Collection-level Postman test on every response (no traceback, SQL or driver names) | PASS on all 145 Newman requests (98 + 12 + 2 + 3 + 30) |
| Docker execution | `docker_execution_check.txt` (this task); full evidence in `DELIVERABELS/Docker_Evidence` (Task 10) | Containers healthy; `/health`, `/health/db`, `/docs` 200 inside the container; migration at head |

## 5. Not measured

- **Line coverage:** `pytest-cov` is not installed in the project environment and was not added.
  The suite has 531 tests; scenario-to-test mapping is in §3.
- **Postman desktop app:** the collection was run with **Newman 6.2.1**, Postman's command-line
  runner, which executes the same collection and test scripts. Newman, its HTML reporter and
  Playwright were installed in a temporary folder, not in the project.

## 6. Files

| Location | Contents |
|---|---|
| `postman/ShopEase_Product_Catalog_Service.postman_collection.json` | The collection: 25 folders, 109 requests, a test on every request (generated by `postman/gen_collection.py`) |
| `postman/ShopEase_Product_Catalog_Service.postman_environment.json` | Environment template: `base_url`, empty `admin_token` and `customer_token`, `run_id`; no secret |
| `Test_Results/pytest/` | `pytest_sqlite.log`, `pytest_mysql.log` (every test by name), `junit_sqlite.xml`, `junit_mysql.xml` |
| `Test_Results/postman/A1_…`, `A3_…`, `A5_…`, `B_live_container.*` | Newman reports: `.html` (requests and responses; `Authorization` headers left out), `.json`, `.txt` (console output) |
| `Test_Results/postman/A2_burst/` | The 12 simultaneous Newman runs and `timeline.txt` |
| `Test_Results/postman/A6_database_verification.md` | Direct SQL checks after run A |
| `Test_Results/postman/summary.json` | Totals of every stage |
| `Test_Results/postman/standin_*.log`, `A4_screenshots.log` | Logs of the test instance, the stand-in and the screenshot run |
| `Test_Results/docker_execution_check.txt` | Docker state, checks inside the container, and the empty test database afterwards |
| `screenshots/01–06_live_*.png` | Swagger UI on the **live** service: overview, list parameters, list executed (200), create without token (401), missing product (404), health (200) |
| `screenshots/07–14_test_*.png` | Swagger UI on the **test instance** with the stand-in ADMIN token: authorized, create (201), duplicate SKU (409), search/filter/sort/page (200), stock-in (201), stock-out insufficient (409), history (200), low stock (200) |

Every screenshot is of a real request sent from Swagger UI in Microsoft Edge (headless, driven by
`scripts/swagger_screenshots.js`). The script adds two things:
- a banner naming the instance and the time;
- `<token hidden>` in place of the token in Swagger UI's generated curl command.

Everything else is the page as the service answered it.

The stand-in tokens were removed from every report (`<stand-in token removed>`). The only token
left in the files is the collection's `forged_token`. It is signed with a random key that was
thrown away, so no service accepts it.

## 7. Reproduce

```powershell
# Stack running with MySQL published: docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
pytest                                                                       # SQLite
$env:CATALOG_SERVICE_TEST_DB="mysql"; $env:MYSQL_DATABASE="shopease_product_catalog_test_db"; pytest
Remove-Item Env:CATALOG_SERVICE_TEST_DB, Env:MYSQL_DATABASE

# Postman with Newman (npm install newman newman-reporter-htmlextra playwright-core in any folder):
python postman/gen_collection.py
$env:NODE_PATH = "<folder>\node_modules"
python -m scripts.run_postman_suite --newman "<folder>\node_modules\.bin\newman.cmd" --screenshots scripts/swagger_screenshots.js
```
