# 09 – Final Completion Report

| | |
| --- | --- |
| Project | ShopEase User Management Microservice (`shopease-user-service`) |
| Period | 10–11 November 2026 (two-day task) |
| Report date | 11 November 2026 |
| Overall status | **Core service complete and verified.** The profile, address and account APIs, JWT verification through the Authentication Service, MySQL with Alembic, and Docker Compose are complete. Screenshots captured. **Not done:** admin endpoints |

Every "Done" below links to evidence produced by commands that were actually run. Nothing is marked as passed without having been executed.

## Summary

The User Service is an independent FastAPI microservice. It stores customer profiles and saved addresses in its own MySQL database, `shopease_user_db`. Every request is authenticated by sending the caller's token to the existing Authentication Service's `verify-token` endpoint, so the service holds no JWT secret.

All 15 planned customer endpoints are implemented, and one customer cannot reach another customer's data. This was checked by 518 automated tests on SQLite and MySQL, by a live audit against the Docker containers with real Authentication Service tokens (73/73), and by a Postman collection run with Newman (38/38 assertions). The flow was also run in the real Swagger UI and captured in 20 screenshots, plus cross-user access denial (21–21c). The planned admin endpoints were not built.

## Requirements status

| Requirement | Status | Evidence |
| --- | --- | --- |
| FastAPI application structure (routers, services, models, schemas, core, database) | ✅ Done | [README](../README.md#folder-structure) |
| MySQL database connects | ✅ Done | `/health/db` returned `connected` from the container; `pytest` MySQL mode 518 passed. [08](08_Docker_Execution_Report.md), [`final_pytest_mysql.txt`](Test_Results/final_pytest_mysql.txt) |
| SQLAlchemy models (`user_profiles`, `user_addresses`) | ✅ Done | [05](05_Database_Schema.md); 17 database-layer tests; `alembic check` reports no differences between the models and the database |
| Alembic migrations | ✅ Done | 2 revisions. At head `4f1a9d27c5e3` in the container; applied automatically on a new empty volume before Uvicorn started; upgrade and downgrade verified. [05](05_Database_Schema.md), [08](08_Docker_Execution_Report.md), [`final_validation_checks.txt`](Test_Results/final_validation_checks.txt) |
| JWT verification through the Authentication Service | ✅ Done | 57 integration tests and 150 security tests. Live: real token 200; missing, malformed or tampered token 401; Authentication Service stopped 503. [06](06_JWT_Integration_Report.md#6-live-test-against-the-running-authentication-service) |
| Profile API (POST, GET, PUT, PATCH, DELETE) | ✅ Done | 87 tests; live audit. [04](04_API_Documentation.md), [07](07_API_Testing_Report.md) |
| Address API (6 endpoints and `GET /addresses/default`) | ✅ Done | 125 tests; live audit; Newman. [04](04_API_Documentation.md#address-endpoints) |
| Default address: one per profile, a transaction, a row lock, promotion on delete | ✅ Done | Tests; live audit; 300 concurrent changes on MySQL left exactly 1 default. [05](05_Database_Schema.md#address-transactions-and-locking) |
| Account management and deactivation (local profile only) | ✅ Done | 67 tests. Live: after deactivation, 403 everywhere, records kept, and the Authentication Service account still active. [04](04_API_Documentation.md#account-management) |
| Ownership restrictions | ✅ Done | Security audit test cases 1–20 (150 tests); live: another user's address gives 404 for GET, PUT, PATCH and DELETE; screenshots 21–21c. [07](07_API_Testing_Report.md) |
| Docker and Docker Compose | ✅ Done | Both containers healthy; MySQL not published; `.env` not in the image; non-root user; data kept across `down`/`up`. [08](08_Docker_Execution_Report.md) |
| Automated tests | ✅ Done | **518 passed** on SQLite and on MySQL. [`final_pytest_sqlite.txt`](Test_Results/final_pytest_sqlite.txt), [`final_pytest_mysql.txt`](Test_Results/final_pytest_mysql.txt) |
| README and reports 01–10 | ✅ Done | [README](../README.md), this folder |
| Word documents | ✅ Done | 4 files in [`Word_Documents/`](Word_Documents/), generated with python-docx from these reports |
| Postman testing | ✅ Done (Newman) | 28 requests, 38/38 assertions, also with the environment template. [`postman_newman_run.txt`](Test_Results/postman_newman_run.txt), [`postman_newman_run_with_environment.txt`](Test_Results/postman_newman_run_with_environment.txt). Not run in the Postman app itself |
| Admin endpoints (list, read, reactivate) | ❌ **Not implemented** | Design in [04](04_API_Documentation.md#planned-admin-endpoints). `require_admin` exists and is tested, but no route uses it |
| Screenshots | ✅ Done | 20 of 20 plus 5 extra (including cross-user access denial), captured from the running system on 11 November 2026. [screenshots/README.md](screenshots/README.md) |

## Test summary

| Suite | Where | Passed | Failed | Not run |
| --- | --- | --- | --- | --- |
| pytest, full suite | SQLite | 518 | 0 | 0 |
| pytest, full suite | MySQL `shopease_user_db` | 518 | 0 | 0 |
| of which: security audit (test cases 1–20 and requirements) | both | 150 | 0 | 0 |
| Live API audit, `scripts/live_api_audit.py` | Docker, real tokens | 73 checks | 0 | – |
| Postman collection, Newman 6.2.1 | Docker, real tokens | 38 assertions (28 requests) | 0 | – |
| Live JWT scenarios ([06, section 6](06_JWT_Integration_Report.md#6-live-test-against-the-running-authentication-service)) | Docker | 8 | 0 | 2 run with the test stand-in only (expired token, inactive Authentication Service account); 2 not applicable (admin) |
| Swagger UI walkthrough (script-driven, Edge) | Docker, real token | 15 steps | 0 | Not clicked by hand |

pytest reports 1 warning: a Starlette deprecation in FastAPI's `TestClient`, which affects only the tests.

## Security summary

- **Identity:**
  - The user ID always comes from the Authentication Service's verify response.
  - A client-supplied `auth_user_id`, `user_id` or `id` is refused with 422.
  - Every query is filtered by the caller's own profile.
- **Errors:**
  - Another customer's address gives the same 404 as a missing one.
  - Errors contain no internal details. An unexpected error returns `500 {"detail":"Internal server error"}`.
- **Secrets:**
  - No JWT secret is held. Passwords come only from `.env`, which Git ignores and the image excludes.
  - No token was found in either service's logs.
  - Saved outputs are sanitized: tokens are shown at most as `eyJhbGciOi…`, and passwords never appear.
- **Audit findings:** 1 fixed (non-JSON 500). Open: no limit on addresses per customer, no rate limiting (low); Swagger UI on by default (informational). Sequential IDs were accepted (informational). See [07](07_API_Testing_Report.md#findings).

## Known limitations

- Admin endpoints are not implemented, so a deactivated profile cannot be reactivated through the API. Its records are kept.
- Every protected request calls the Authentication Service, with no caching. If that service is down, protected endpoints return 503.
- There is no limit on addresses per customer, and no rate limiting.
- An expired real token, and a token from an account deactivated in the Authentication Service, were tested only with the test stand-in, not live.
- The service is not part of the platform-level Compose file or the API gateway. That was deliberate: no other microservice was to be integrated.

## Pending items

| Item | Owner action |
| --- | --- |
| Admin endpoints (list, read, reactivate) | Future work |
| Address limit and rate limiting (audit findings 2 and 3) | Future work |
| Post the Teams updates | Text in [10](10_Teams_Progress_Updates.md) |
| Commit and push | To be done manually by the author. Nothing was committed or pushed |

## Confirmation

- [x] `shopease-auth-service` and `shopease-product-service` were not modified. The Authentication Service was only started with its own Compose file, and test users were registered through its API.
- [x] Nothing was committed or pushed to GitHub. The enclosing repository's last commit is still `f43126c`.
- [x] `.env` is not tracked by Git (`git check-ignore`: `.gitignore:6:.env`).
- [x] No secret, password or whole token appears in any document or saved output. The scan covered 44 files and the 4 Word documents, checking for the values from both services' `.env` files and for JWTs (see the end of [`final_validation_checks.txt`](Test_Results/final_validation_checks.txt)).
- [x] Screenshots captured and checked for tokens and passwords: masked in the page and checked before each capture, then each image reviewed.
