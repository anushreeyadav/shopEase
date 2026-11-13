# Final completion checklist

ShopEase Product Catalog Service 1.0.0, updated 13 November 2026. **Completed** means implemented *and* verified,
with the evidence named. **Pending** means not done yet. **Blocked** means it cannot be done without something
outside this project.

## Final audit (Task 12)

`python -m scripts.final_audit`, read-only, 2026-11-13 12:38:28 UTC: 50 checks passed, 0 failed
(`Test_Results/final_audit/03_final_audit.txt`).

| Audit item | Status | Evidence |
|---|---|---|
| All required endpoints | Completed | 20 of 20 routes in the live OpenAPI, no extra route; 17 live probes (public 200, unknown 404, invalid ID 422, admin routes without a token 401) |
| Database migration | Completed | `alembic current` in the container = `c4a7d2e91b30 (head)`; `alembic check`: no differences; 4 tables, 2 foreign keys (RESTRICT), 11 CHECK constraints |
| JWT integration with the existing Auth Service | Completed (real customer token used live; real ADMIN token: Blocked) | Real Auth Service: no token → 401, forged ADMIN token → 401; Catalog forwards the forged token → 401; real customer token → 403 on every ADMIN route (`live_customer/live_customer_check.txt`, 17 of 17) |
| All mandatory test cases | Completed on the test instance and in pytest; live: 6, 18, 19 passed, 14 Blocked, 3 partly | `final_audit/01–02` (525 + 6 skipped / 531 passed); `Task11_API_Test_Report.md` |
| Docker Compose execution | Completed | Both containers running and healthy; named volume present; `Docker_Evidence/01–11` |
| Documentation and Word files | Completed | 9 `.docx` in `Word_Documents/`, opened in Microsoft Word 16 and exported to PDF to check the layout |
| `.env` not in deliverables | Completed | No `.env*` in `DELIVERABELS/`; none of the `.env` secret values in any project or deliverable file; no `.env` in the running image |
| No GitHub push or commit | Completed (by the assistant) | No Git command in Tasks 9–12 or in the 13 November follow-up; one read-only `git diff --stat` in Task 8, disclosed at the time; no commit, push or GitHub operation. The folder has no `.git`; the parent repository listed it as untracked. Confirm with `git status` / `git log` yourself |

## Requirements

| Item | Status | Evidence / next step |
|---|---|---|
| Project setup, configuration, models | Completed | `tests/test_scaffold.py`, `test_config.py`, `test_models.py` |
| Alembic migrations on MySQL 8.4 | Completed | `Test_Results/Migration_Execution_Report.md` |
| JWT integration (Auth Service unchanged) | Completed | `02_JWT_Integration.md`, `auth_integration_logs/` |
| Category APIs | Completed | `tests/test_category_api.py`, transcripts |
| Product APIs | Completed | `tests/test_product_api.py`, `product_api_logs/` |
| Search, filters, paging, sorting | Completed | `tests/test_product_search.py`, `product_search_logs/` |
| Inventory and history | Completed | `tests/test_inventory_*.py`, `inventory_logs/` |
| Docker and Compose | Completed | `Docker_Evidence/` |
| 20 mandatory scenarios, test instance + pytest | Completed | `Task11_API_Test_Report.md`, `postman/` reports |
| Scenario 18 (customer → 403) on the live stack | Completed | `Test_Results/live_customer/live_customer_check.txt`: real customer account, 17 passed, 0 failed (13 Nov 2026); `screenshots/submission/10_.../customer_403_live.png` |
| 20 mandatory scenarios on the live stack | Blocked (6, 18, 19 passed live) | 14 scenarios need an ADMIN token. The account `catalog.admin@example.com` is registered (role USER); granting the ADMIN role needs one UPDATE in the Auth Service database, which the permission system blocked for the assistant: the Auth Service owner runs it (see below) |
| Postman collection and environment template | Completed | `postman/` (no secret in the template) |
| Word documents (9) | Completed | `Word_Documents/` (`python -m scripts.build_word_documents`) |
| README, endpoint reference, schema SQL reference | Completed | `README.md`, `API_Documentation/API_Endpoint_Reference.md`, `Database_Evidence/schema_reference.sql` |
| Test execution summary | Completed | `Test_Results/Test_Execution_Summary.md` |
| Teams daily update templates | Completed | `Progress_Reports/Teams_Daily_Update_Templates.md` |
| Screenshot folders and checklist | Completed | `screenshots/submission/01–18`, `screenshots/SCREENSHOT_CHECKLIST.md` |
| 18 submission screenshots | Completed | All 18 items captured (13 Nov 2026); ADMIN items on the test instance (`_test_instance`); item 1 captured manually (3 images). Collected in `screenshots/ShopEase_Submission_Screenshots.pptx` |
| Line coverage | Completed | 96 % of `app/` (1164 statements, 41 missed), 531 passed: `Test_Results/final_audit/04_coverage_mysql.txt` (pytest-cov 7.1.0 installed in `.venv`, not added to `requirements.txt`) |
| Evidence `.log` files in Git | Completed | `.gitignore` exception `!DELIVERABELS/**/*.log`; checked by the final audit (28 files). Confirm with `git check-ignore -v` on one of them: it should print nothing |
| Git commit / push | Pending (your decision) | Not done by the assistant |

## Still to do (you)

1. **Optional, for live ADMIN testing:** grant the ADMIN role to the registered account (this changes the Authentication
   Service's database, as its README describes):
   ```powershell
   docker exec -it shopease-auth-service-auth-mysql-1 sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'
   ```
   ```sql
   UPDATE users SET role = 'ADMIN' WHERE email = 'catalog.admin@example.com';
   ```
   Then ask for the live run: the Postman collection and the ADMIN screenshots can be repeated on port 8006.
2. **Git:** review `git status`, commit and push yourself.
