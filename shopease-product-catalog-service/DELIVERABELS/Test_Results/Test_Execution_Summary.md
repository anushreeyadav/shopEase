# Test execution summary

ShopEase Product Catalog Service 1.0.0, 12–13 November 2026 (times UTC). Every figure below comes from a file in
this folder. Full analysis: [Task11_API_Test_Report.md](Task11_API_Test_Report.md) and
`Word_Documents/API_Testing_Report.docx`.

## Latest runs (final audit, Task 12)

| Run | Recorded | Result | Log |
|---|---|---|---|
| pytest, whole suite, SQLite | 15:25:44 | **525 passed, 6 skipped** (the 6 need MySQL), exit code 0 | `final_audit/01_pytest_sqlite.log` |
| pytest, whole suite, MySQL 8.4 test database | 15:26:27 | **531 passed**, exit code 0 | `final_audit/02_pytest_mysql.log` |
| Final audit, read-only (`python -m scripts.final_audit`) | 13 Nov 11:59:40 | **50 checks passed, 0 failed**: endpoints, migration, JWT, Docker, secrets, `.env`, evidence logs | `final_audit/03_final_audit.txt` |
| pytest with line coverage, MySQL 8.4 test database | 13 Nov | **531 passed**, coverage of `app/` **96 %** (1164 statements, 41 missed) | `final_audit/04_coverage_mysql.txt` |
| Live customer check: real customer account, running container | 13 Nov 11:37:20 | **17 passed, 0 failed** (403 on every ADMIN route, 200 on public reads) | `live_customer/live_customer_check.txt` |

## Postman (Newman 6.2.1), Task 11, 14:04–14:06

| Stage | Where | Result |
|---|---|---|
| A1: scenarios 1–20 | Test instance (port 8016, test database, stand-in Authentication Service) | 98 requests, 308 assertions, 0 failed |
| A2: 12 Newman processes at once, one stock-out each (stock 5) | Test instance | 5 × 201, 7 × 409, 0 assertions failed |
| A3: consistency after the burst | Test instance | 2 requests, 7 assertions, 0 failed |
| A5: cleanup requests | Test instance | 3 requests, 6 assertions, 0 failed |
| A6: direct SQL checks | MySQL test database | 11 of 11 PASS |
| B: folders 06, 19 and public reads | **Live container, real Authentication Service** | 30 requests, 110 assertions, 0 failed |

Source: `postman/summary.json` and the reports beside it.

## Mandatory scenarios

| Status | Scenarios |
|---|---|
| Passed in pytest and on the test instance | 1–20 (all) |
| Passed live | 6, 18 (real customer account), 19 |
| Partly live (correct responses; the live database has no products) | 5, 11, 12 |
| Blocked live: need an ADMIN token (the Authentication Service has no ADMIN account) | 1–4, 7–10, 13–17, 20 |
| Failed | none |

## Screenshots

All 18 submission screenshots are captured (`../screenshots/submission/`; item 1, VS Code, taken manually) and
collected in `../screenshots/ShopEase_Submission_Screenshots.pptx`. See `../screenshots/SCREENSHOT_CHECKLIST.md`.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m pytest
$env:CATALOG_SERVICE_TEST_DB="mysql"; $env:MYSQL_DATABASE="shopease_product_catalog_test_db"; .\.venv\Scripts\python.exe -m pytest
$env:CATALOG_SERVICE_TEST_DB="mysql"; $env:MYSQL_DATABASE="shopease_product_catalog_test_db"; .\.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing   # needs: pip install pytest-cov
Remove-Item Env:CATALOG_SERVICE_TEST_DB, Env:MYSQL_DATABASE
$env:CUSTOMER_EMAIL="..."; $env:CUSTOMER_PASSWORD="..."; .\.venv\Scripts\python.exe -m scripts.live_customer_check
.\.venv\Scripts\python.exe -m scripts.final_audit
```
