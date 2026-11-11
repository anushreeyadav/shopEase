# 07 – API Testing Report: Security Audit

| | |
| --- | --- |
| Date | 11 November 2026 |
| Scope | ShopEase User Service: all 15 API endpoints (profile, address, account) |
| Focus | One customer must never read or change another customer's profile or addresses |
| Test file | [`tests/test_security_audit.py`](../tests/test_security_audit.py) (150 tests), with the Authentication Service stand-in [`tests/fake_auth_service.py`](../tests/fake_auth_service.py) |
| Environment | Windows 11, Python 3.11.0, pytest 9.2.0, FastAPI TestClient. Database: SQLite in memory, and MySQL 8.4 `shopease_user_db` (container `user-mysql`, Alembic head `4f1a9d27c5e3`) |
| Result | **150 passed, 0 failed, 0 skipped** on SQLite and on MySQL. Full suite: **510 passed** on both at the time of the audit, and **518 passed** in the final run |
| Live tests (added later the same day) | Against the Docker containers with real Authentication Service tokens. Scripted audit: **73/73 checks passed**. Postman collection with Newman: **38/38 assertions passed**. See [Live API tests](#live-api-tests-docker-real-authentication-service) |

**Only tests that were actually run are marked as passed.** Tests that were not run are listed under [Not executed](#not-executed).

## How the tests work

- **Real authentication path.** The other API test files replace `get_current_authenticated_user` to set the caller directly. These audit tests do **not**. Every request carries a signed JWT and goes through the real `HTTPBearer` parsing, `verify_access_token()`, and the HTTP call to `POST /api/auth/verify-token`.
- **Authentication Service stand-in.** The real Authentication Service was **not running** (port 8001 unreachable on 11 November 2026). The stand-in implements the contract read from the `shopease-auth-service` code:
  - HS256 tokens with `sub`, `role`, `iat` and `exp`
  - 200 `{valid, user}`, 401 `Could not validate credentials`, and 403 `Inactive user`
  - real signature checks and expiry checks
  The signing key exists only in the test module, and the User Service never has it.
- **Users.** Customer 7 (the victim), customer 8 (the attacker), and user 9, whose Authentication Service account is inactive.
- **Database.** Each test runs in a transaction that is rolled back. After the MySQL runs, `user_profiles` and `user_addresses` had **0 rows**.

## Results: test cases 1–20

Run on 11 November 2026, 10:24. Every test passed on SQLite and on MySQL.

| # | Test case | Expected | Actual | Tests | Result |
| --- | --- | --- | --- | --- | --- |
| 1 | Access profile without JWT | 401, `WWW-Authenticate: Bearer`, Authentication Service not called | 401 `Could not validate credentials`, header present, 0 calls to the Authentication Service | 1 | ✅ Pass |
| 2 | Access profile with invalid JWT | 401 for each kind of invalid token | 401 for each: garbage, three random parts, signed with the wrong key, `alg: none` with role ADMIN, an oversized token (5,000 chars), customer 7's claims with customer 8's signature, and the `Basic`, `Token` and `bearer-x` schemes. No profile data in any response | 9 | ✅ Pass |
| 3 | Access profile with expired JWT | 401 | 401 `Could not validate credentials`, for a correctly signed token whose `exp` had passed | 1 | ✅ Pass |
| 4 | Access profile with valid JWT | 200 with own profile | 200, own profile. The token was sent only as `Authorization` in a `POST /api/auth/verify-token` with an empty body | 1 | ✅ Pass |
| 5 | Create duplicate profile | 409, still one row | 409 `User profile already exists`. 1 row for `auth_user_id` 7, original name unchanged | 1 | ✅ Pass |
| 6 | Retrieve own profile | 200, own data | 200, `auth_user_id` 7 with own name and phone. Customer 8's data never appeared | 1 | ✅ Pass |
| 7 | Update own profile | 200, saved | PATCH 200 (phone normalized), PUT 200. The database row matched | 1 | ✅ Pass |
| 8 | Access another user's profile | Never possible | See [test case 8 in detail](#test-case-8-in-detail) | 23 | ✅ Pass |
| 9 | Create own address | 201, owned by own profile | 201. `user_id` = own profile ID in both the response and the database, even with `?user_id=999` in the query | 1 | ✅ Pass |
| 10 | Retrieve own addresses | Own addresses only | 200, exactly customer 7's 2 addresses, even with customer 8's profile ID in `?user_id=` | 1 | ✅ Pass |
| 11 | Update own address | 200, saved | 200. City changed in the database | 1 | ✅ Pass |
| 12 | Delete own address | 200, row gone | 200. Row deleted | 1 | ✅ Pass |
| 13 | Read another user's address by changing `address_id` | 404, the same as a missing ID | Customer 8 walked every ID from 1 to 4 above the highest. Each ID other than their own got 404 `Address not found`, with the same body and length as a nonexistent ID (999999). Their own ID got 200 | 1 | ✅ Pass |
| 14 | Modify another user's address | 404, nothing changed | PUT, DELETE and `PATCH .../default` on customer 7's address, with `?user_id=`, `?auth_user_id=7` and `X-User-Id: 7` added: each got 404. The row was unchanged and still existed, and neither customer's default changed. A PUT with `user_id` in the body (to move an address to another owner) got 422 | 4 | ✅ Pass |
| 15 | Set an address as default | 200, the only default | 200, `is_default: true`. Exactly 1 default in the database, and `GET .../default` returns it | 1 | ✅ Pass |
| 16 | Try to create two default addresses | Never two | Two POSTs with `is_default: true` left 1 default (the newer one). PUT with `is_default` got 422. A **direct database insert** of a second default (bypassing the service) was refused with `IntegrityError` by `uq_user_addresses_one_default_per_user` | 2 | ✅ Pass |
| 17 | Only one default exists | Exactly 1 after every operation | Over 4 creates, 3 default changes and 2 deletes, there was exactly 1 default after each step, matching `GET .../default` | 1 | ✅ Pass |
| 18 | Deactivate a profile | 200, record kept | 200 `profile_status: DEACTIVATED`. Row kept with `is_active = 0`, data and addresses unchanged | 1 | ✅ Pass |
| 19 | Inactive profile cannot manage addresses | 403 on every address endpoint | All 7 address endpoints returned 403 `User profile is deactivated`. The address and the default were unchanged | 7 | ✅ Pass |
| 20 | User Service does not change the Authentication Service account | No change, verify-token calls only | The stand-in's user records were identical before and after deactivations through both endpoints. The same token still verified as active. Every request the User Service sent was `POST /api/auth/verify-token` with no body. A code scan found exactly one outbound HTTP call in `app/` (`security.py`, to `auth_service_verify_url`) | 2 | ✅ Pass |

Tests 16–17 are also covered under real concurrency. On the same day, a live check against MySQL ran 300 concurrent default changes from 20 threads: **300 succeeded, 1 default at the end, 0 rows left** ([`security_audit_concurrency_mysql.txt`](Test_Results/security_audit_concurrency_mysql.txt)).

### Test case 8 in detail

Customer 8 is authenticated and tries to reach customer 7's profile:

| Attempt | Result |
| --- | --- |
| `GET /api/users/profile` with their own token | Only ever their own profile |
| `?auth_user_id=7`, `?user_id=7`, `?id=1`, `?profile_id=1` | Ignored; their own profile returned |
| Headers `X-User-Id`, `X-Auth-User-Id`, `X-Forwarded-User`, `X-Remote-User: 7` | Ignored |
| `auth_user_id`, `id`, `user_id`, `is_active`, `email`, `role` in the body | 422. Neither profile changed |
| `/api/users/7`, `/api/users/1`, `/api/users/profile/7`, `/api/users/7/profile` (GET, PATCH, DELETE) | 404 or 405: no such route. No data returned |
| PUT, contact update and deactivate with customer 7's ID in the query or headers | Only customer 8's own profile changed. Customer 7's name, phone and active status were unchanged |
| `GET /api/users/account` with `?auth_user_id=7` and `X-User-Id: 7` | Customer 8's own account and profile only |

## Results: security requirements

| Requirement | How it was checked | Tests | Result |
| --- | --- | --- | --- |
| No client-supplied user ID can override the JWT identity | Test cases 8, 9, 10 and 14: IDs in the query, headers, body and path. The OpenAPI schema has no `auth_user_id`, `user_id` or token parameter on any endpoint, and no identity field in any request body | 23 + 1 | ✅ Pass |
| All queries scoped to the authenticated owner | Code review (below), test cases 8, 10, 13 and 14, and fault injection | – | ✅ Pass |
| Missing or invalid authentication returns 401 | **Every endpoint** (15) × missing, invalid and expired token = 45 cases. All 401 with the same body. No data changed | 45 | ✅ Pass |
| Forbidden operations return 403 | **Every endpoint** with an inactive Authentication Service account: 15 × 403 `Inactive user`. **Every endpoint** needing a profile, after deactivation: 14 × 403 `User profile is deactivated` | 29 | ✅ Pass |
| Foreign resources return 404 (no enumeration) | Each of the 4 address-ID endpoints: another customer's address and a nonexistent ID give **byte-identical** responses (status, body, content type) | 4 | ✅ Pass |
| No passwords or authentication secrets | No `password`, `secret`, `token` or `hash` property in any OpenAPI schema. No such word, and no token, in any GET response. No credential columns (`test_database_layer.py`). No JWT secret setting (`test_scaffold.py`). `.env` is gitignored, and the only secrets are the MySQL passwords (`SecretStr`) | 2 | ✅ Pass |
| No token leakage in logs | All 15 endpoints called with 5 tokens (valid, expired, inactive user, forged, garbage), plus a database error and an Authentication Service outage, with DEBUG logging. No token or token signature appeared in any log record or response, and neither did the words `Authorization` or `Bearer`. All 5,453 saved log lines were also scanned, as were all result files: nothing found | 1 | ✅ Pass |
| No sensitive internal details in responses | A database error with SQL, a password and a host in its message gives 503 `Service temporarily unavailable`. `RuntimeError` and `KeyError` with paths and secrets give 500 `Internal server error`. None of these details appear in responses or logs. Authentication Service 500/502 bodies with tracebacks and secrets, and a malformed 200, give 503 `Authentication service unavailable`, never passed through. Validation errors do not repeat the submitted value | 12 + 1 | ✅ Pass |
| Route inventory | The audit expects exactly 15 routes. A new route makes this test fail, so it gets reviewed. The all-endpoint tests pick new routes up automatically from OpenAPI | 1 | ✅ Pass |

## Code review

| Area | Finding |
| --- | --- |
| Identity source | `get_current_authenticated_user()` is the only source of `auth_user_id`, and every protected route depends on it. No route has a user or profile ID parameter |
| Profile queries | One query function, `user_service._find_profile`: `WHERE auth_user_id = :caller`. All profile, address and account operations go through `get_active_profile`, which uses it |
| Address queries | All 4 address queries filter on `user_id = :caller_profile_id`. A single address is looked up by `id AND user_id`, so another customer's address is simply not found |
| Writes | Every address write locks the caller's own profile row (`FOR UPDATE`) and runs in one transaction with rollback |
| Mass assignment | Every request schema has `extra="forbid"`. `id`, `user_id`, `auth_user_id`, `is_active` and `is_default` (on PUT) are rejected with 422 |
| Outbound calls | One: `POST` to `AUTH_SERVICE_VERIFY_URL`. Redirects are not followed, so the token cannot be sent anywhere else |
| Logging | 5 log statements in `app/`, all class names, status codes or route paths. The token is never passed to a logger |

## Findings

| # | Severity | Finding | Status |
| --- | --- | --- | --- |
| 1 | Low | An unexpected exception (not a database error) returned Starlette's plain-text `Internal Server Error`, not the JSON error format, and depended on the server's default logging | **Fixed during the audit.** `app/exception_handlers.py` now returns `500 {"detail": "Internal server error"}` and logs only the exception class and route. Removing the fix makes 2 audit tests fail |
| 2 | Low | No limit on the number of addresses per customer: a customer can create very many rows | Open. Recommend a limit (for example 20) in `address_service.create_address` |
| 3 | Low | No rate limiting, so a stolen or valid token can make unlimited requests. Each one also costs a verify-token call | Open. Recommend rate limiting at the API gateway |
| 4 | Info | Swagger UI and OpenAPI are enabled by default (`DOCS_ENABLED=true`) | Set `DOCS_ENABLED=false` in production |
| 5 | Info | Responses include sequential database IDs (`id`, `user_id`) | Accepted: IDs are only ever looked up inside the caller's own data, and foreign IDs give the same 404 as missing ones (test case 13) |

No finding allowed one customer to read or change another customer's data.

## Fault injection

To show the tests detect real vulnerabilities, each fault below was put into the code on its own. The audit suite was run, and the file was restored.

| Fault | Audit tests failing |
| --- | --- |
| Address lookup no longer filtered by owner | 8 failed |
| Profile lookup returns the first profile instead of the caller's | 1 failed, 46 errors |
| Access token written to the log | 1 failed |
| No JSON handler for unexpected errors (the code before finding 1 was fixed) | 2 failed |
| Authentication Service error body passed to the client | 2 failed |

All files were restored and compared with the originals afterwards, and the suite passed again.

## Saved results

All in [`Test_Results/`](Test_Results/). Every file was scanned for JWTs (`eyJ…`), `Bearer` values, the test signing key, and the MySQL passwords from `.env`. None were found, so nothing needed redacting. All test data is fictional (`*.test@example.com`).

| File | Contents |
| --- | --- |
| `security_audit_pytest_sqlite.txt`, `security_audit_pytest_mysql.txt` | `pytest -v -rA` output of the audit suite: 150 passed each |
| `security_audit_junit_sqlite.xml`, `security_audit_junit_mysql.xml` | The same results as JUnit XML |
| `security_audit_app_log_sqlite.txt`, `security_audit_app_log_mysql.txt` | Every application and HTTP log record at DEBUG level during the audit runs (1,942 and 3,511 lines). Used for the token-leakage check |
| `security_audit_concurrency_mysql.txt` | Live concurrency check: 300 concurrent default changes, 1 default |
| `full_suite_pytest_sqlite.txt`, `full_suite_pytest_mysql.txt` | The whole test suite: 510 passed each |
| `final_pytest_sqlite.txt`, `final_pytest_mysql.txt` | Final run of the whole suite: 518 passed each |
| `final_live_api_audit.txt` | Live audit against the Docker containers: 73/73 |
| `postman_newman_run.txt` | Postman collection run with Newman: 28 requests, 38/38 assertions |
| `postman_newman_run_with_environment.txt` | Same collection run with the environment template (`-e`): 28 requests, 38/38 assertions |
| `ShopEase_User_Service.postman_collection.json`, `ShopEase_User_Service.postman_environment.json` | Copies of the Postman collection and the environment template (base URLs only, no credentials) |
| `screenshot_capture_run.txt` | Record of the live screenshot capture runs |
| `final_validation_checks.txt` | Token search in both services' logs, database rows after the audit, Alembic in the container, Compose validation, Git |

To rerun:

```powershell
pytest tests/test_security_audit.py -v
$env:USER_SERVICE_TEST_DB = "mysql"; pytest tests/test_security_audit.py -v; Remove-Item Env:USER_SERVICE_TEST_DB
```

## Live API tests (Docker, real Authentication Service)

Run on 11 November 2026, after the Docker work in [08](08_Docker_Execution_Report.md):
- **User Service:** in its container on `127.0.0.1:8002`, with MySQL in `user-mysql`.
- **Authentication Service:** in its own Compose project on `127.0.0.1:8001`, with its files unchanged.
- **Users:** new test users were registered and logged in on the Authentication Service, and every call used their real access tokens.

### Scripted audit: `scripts/live_api_audit.py`

Two real users, A (auth id 7) and B (auth id 8). A check passes only if both the HTTP status and the stated condition match. **73 checks: 73 passed, 0 failed.** Output: [`final_live_api_audit.txt`](Test_Results/final_live_api_audit.txt).

The audit was run three times, with 73/73 each time:
- **First run** (auth users 2 and 3): from a scratch copy of the script. Its output printed part of each login token, so it was redacted afterwards, and the redaction step also deleted five result lines. That output was discarded, not repaired.
- **Second run** (auth users 5 and 6): from `scripts/live_api_audit.py`, which redacts tokens itself. Its token log search covered only one of its two tokens.
- **Third run** (auth users 7 and 8): the evidence shown here, including the log search for both tokens.

| Area | Checks | What was shown |
| --- | --- | --- |
| Health | 3 | `/health`, `/health/db` (`database: connected`), `/` |
| Real users | 4 | Register and log in A and B on 8001 |
| JWT verification | 6 | No token, malformed token, altered signature, `Basic` scheme: all 401. A's real token: 200, with `auth_user_id` equal to A's ID from the Authentication Service |
| Profile | 9 | 404 before creation; a client-supplied `auth_user_id` refused (422); create 201, linked to the token's identity; second create 409; GET; PUT clears omitted fields; PATCH; invalid phone 422 |
| Account | 5 | Contact update normalizes the phone; email in the contact update refused (422); account shows `profile_status: ACTIVE` |
| Addresses | 22 | Empty list; no default 404; first address becomes the default; `is_default: true` on create moves the default; client `user_id` refused; type `WORK` and missing city refused; exactly one default, listed first; GET; PUT; set the default; the default changes; deleting the default promotes the oldest remaining address; deleted address 404; ID 0 gives 422 |
| Ownership | 11 | B's GET, PUT, PATCH default and DELETE on A's addresses: all 404. B's list does not include A's. A cannot read B's address. A's addresses unchanged afterwards. The admin route `/api/users/{id}` does not exist (404) |
| Deactivation | 13 | `PATCH /account/deactivate` 200 with `authentication_account_changed: false`. Then 403 on profile GET and PATCH, address list, create and default, account GET, and deactivate again. A's token is still valid at the Authentication Service (`is_active: true`), A can still log in, and B is unaffected |

After the run, the database shows A's profile with `is_active = 0`, and A's two addresses still stored with one default. No profile has more than one default address. Neither service's log contains either token, whole or by its signature ([`final_validation_checks.txt`](Test_Results/final_validation_checks.txt)).

### Postman collection with Newman

[`postman/ShopEase_User_Service.postman_collection.json`](../postman/ShopEase_User_Service.postman_collection.json) was run with Newman 6.2.1, Postman's command-line runner: **28 requests, 38 assertions, 0 failed**. It covers health, register, login and verify on 8001, the no-token 401, all profile, account and address endpoints, default promotion, deactivation, and login still working afterwards. Output: [`postman_newman_run.txt`](Test_Results/postman_newman_run.txt). The environment template [`postman/ShopEase_User_Service.postman_environment.json`](../postman/ShopEase_User_Service.postman_environment.json) (base URLs only) was run the same way: 38/38 ([`postman_newman_run_with_environment.txt`](Test_Results/postman_newman_run_with_environment.txt)).

Cross-user access was also captured in Swagger UI: user B gets 404 `Address not found` for GET and DELETE on user A's address, and user A still reads it unchanged (screenshots 21, 21b, 21c).

### The test plan, mapped to these runs

| # | Endpoint | Scenario | Expected | Actual | Pass |
| --- | --- | --- | --- | --- | --- |
| 1 | `GET /health` | Service up | 200 | 200 | ✅ |
| 2 | `GET /health/db` | Database up | 200 | 200, `connected` | ✅ |
| 3 | `POST /api/users/profile` | Create profile | 201 | 201 | ✅ |
| 4 | `POST /api/users/profile` | Create again | 409 | 409 | ✅ |
| 5 | `GET /api/users/account` | Account and profile | 200 | 200, `ACTIVE` | ✅ |
| 6 | `PATCH /api/users/account/contact` | Update phone | 200 | 200, `+919876543210` | ✅ |
| 7 | `POST /api/users/addresses` | First address | 201, is_default true | 201, true | ✅ |
| 8 | `POST /api/users/addresses` | Second address | 201, is_default false | 201, false (Newman) | ✅ |
| 9 | `GET /api/users/addresses` | List | 200, default first | 200, default first | ✅ |
| 10 | `PATCH /api/users/addresses/{id}/default` | Switch default | 200, exactly one default | 200, one default | ✅ |
| 11 | `GET /api/users/addresses/default` | Default address | 200 | 200, the new default | ✅ |
| 12 | `DELETE /api/users/addresses/{id}` | Delete default | 200, oldest remaining becomes default | 200, oldest promoted | ✅ |
| 13 | `GET /api/users/addresses/{id}` | Second user, first user's address | 404 | 404 | ✅ |
| 14 | Any endpoint | No token | 401 | 401 | ✅ |
| 15 | `PATCH /api/users/account/deactivate` | Deactivate | 200, record kept | 200; row kept with `is_active = 0` | ✅ |
| 16 | `GET /api/users/addresses` | After deactivation | 403 | 403 | ✅ |
| 17 | `POST /api/auth/login` on 8001 | Login still works after deactivation | 200 | 200 | ✅ |

These were run as scripted HTTP calls and with Newman. The customer flow was then run once more in the real Swagger UI, driven by a script in Edge, and captured as screenshots 05–18 ([screenshots/README.md](screenshots/README.md)); every step returned the expected status.

## Not executed

These were **not run** and are **not** counted as passed:

| Test | Why not run | Needed |
| --- | --- | --- |
| A real expired token from the Authentication Service (after its 30-minute expiry) | It needs a 30-minute wait, or a change to the Authentication Service's expiry setting, which was not to be modified | Log in, wait 30 minutes, call any endpoint: expect 401. Covered by automated test case 3 with the stand-in |
| A token of a user deactivated **in the Authentication Service** | It needs that account deactivated in the Authentication Service | Covered by automated test case 4 (403) with the stand-in |
| Admin scenarios (USER token gives 403, ADMIN token gives 200) | Admin endpoints are not implemented | Implement the endpoints first |
| A walkthrough in Swagger UI clicked by hand | The walkthrough was run in Swagger UI by a script (screenshots 05–18), not by a person | Optional: repeat by hand |

## Summary

- **Automated:** 150 security tests run, 150 passed, 0 failed, on SQLite and on MySQL. The whole suite is now 518 tests, all passed on both.
- **Live:** 73/73 scripted checks and 38/38 Newman assertions passed against the Docker containers with real Authentication Service tokens.
- **Cross-customer access:** no path found, either in the automated tests or live. Profile and address access is always scoped to the identity verified by the Authentication Service. Foreign addresses cannot be told apart from missing ones.
- **Findings:** 1 low issue fixed (non-JSON 500), 2 low and 2 informational recommendations open.
- **Outstanding:** a live expired token, a live token from an inactive Authentication Service account, and admin scenarios. The Swagger UI walkthrough was done by script, with screenshots.
