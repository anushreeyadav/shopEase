# 03 – Day 2 Progress

| | |
| --- | --- |
| Date | 11 November 2026 |
| Goal | Address API, account management, Docker execution, testing, final documents |
| Status | **Address and account management, the security audit, Docker, the live test with the real Authentication Service, documents and Word versions are complete.** Screenshots captured (20 of 20, plus 5 extra). Admin endpoints are not done |

## Completed

| Item | Evidence |
| --- | --- |
| **Address API**: `POST`, `GET` `/api/users/addresses`; `GET`, `PUT`, `DELETE` `/api/users/addresses/{address_id}`; `PATCH .../{address_id}/default` | `app/routers/address_routes.py`, `app/services/address_service.py`, `app/schemas/address_schema.py`, [04](04_API_Documentation.md#address-endpoints) |
| **Default delivery address**: `GET /api/users/addresses/default` | `address_service.get_default_address` |
| **Account management**: `GET /api/users/account`, `PATCH /api/users/account/contact`, `PATCH /api/users/account/deactivate` | `app/routers/account_routes.py`, `app/services/account_service.py`, `app/schemas/account_schema.py`, [04](04_API_Documentation.md#account-management) |
| Address types `HOME`, `OFFICE`, `OTHER`: migration `4f1a9d27c5e3` converts `WORK` to `OFFICE`; upgrade, downgrade and upgrade verified on MySQL with a test row | `alembic/versions/4f1a9d27c5e3_...py`, [05](05_Database_Schema.md#4f1a9d27c5e3-rename-work-address-type-to-office) |
| Address ownership: every lookup filtered by the caller's profile; another user's address returns the same 404 as a missing one | `address_service._get_owned_address` |
| Default-address transactions: one transaction per write, owning profile row locked with `SELECT ... FOR UPDATE`, rollback on any failure, unique key as a backstop | `address_service._transaction`, [05](05_Database_Schema.md#address-transactions-and-locking) |
| Live concurrency check on MySQL: 300 concurrent default changes from 20 threads, all succeeded, exactly 1 default | [05](05_Database_Schema.md#concurrency-check-against-mysql-11-november-2026) |
| Authentication account status vs User Service profile status documented | [04](04_API_Documentation.md#authentication-account-status-vs-user-service-profile-status) |
| 04, 05, 02, README, 07 test plan, screenshots list and checklist updated to the real paths | `DELIVERABELS/` |
| **Security audit**: test cases 1–20 and the security requirements, 150 tests through the real token-verification path. One low finding fixed (unexpected errors now return JSON 500 without details) | `tests/test_security_audit.py`, [07](07_API_Testing_Report.md) |
| **Docker**: both containers healthy, migrations before Uvicorn (also on a new empty volume), MySQL not published, data kept across `down`/`up` | `Dockerfile`, `docker-compose.yml`, `docker-compose.dev.yml`, [08](08_Docker_Execution_Report.md) |
| **Live test with the real Authentication Service**: real tokens verified from inside the container through `host.docker.internal:8001`. Tampered or missing token 401; the Authentication Service stopped gives 503 | [06, section 6](06_JWT_Integration_Report.md#6-live-test-against-the-running-authentication-service) |
| **Final live audit**: every endpoint against the containers with two real users, including cross-user access and deactivation. **73/73 checks passed** | `scripts/live_api_audit.py`, [`Test_Results/final_live_api_audit.txt`](Test_Results/final_live_api_audit.txt) |
| **Postman collection**: 28 requests, run with Newman, **38/38 assertions passed** | `postman/` (collection and environment template; copies in `Test_Results/`), [`postman_newman_run.txt`](Test_Results/postman_newman_run.txt), [`postman_newman_run_with_environment.txt`](Test_Results/postman_newman_run_with_environment.txt) |
| README completed; reports 01–10; four Word documents | `README.md`, `DELIVERABELS/`, `DELIVERABELS/Word_Documents/` |

### Account-management requirements

| # | Requirement | Endpoint | Status |
| --- | --- | --- | --- |
| 1 | Retrieve account and profile information | `GET /api/users/account` | ✅ new |
| 2 | Update contact information | `PATCH /api/users/account/contact` | ✅ new |
| 3 | Update profile details | `PUT` / `PATCH /api/users/profile` | ✅ Day 1, reviewed |
| 4 | Retrieve all saved addresses | `GET /api/users/addresses` | ✅ reviewed |
| 5 | Retrieve the default delivery address | `GET /api/users/addresses/default` | ✅ new |
| 6 | Change the default delivery address | `PATCH /api/users/addresses/{address_id}/default` | ✅ reviewed |
| 7 | Delete saved addresses | `DELETE /api/users/addresses/{address_id}` | ✅ reviewed |
| 8 | Deactivate the local user profile | `PATCH /api/users/account/deactivate` (also `DELETE /api/users/profile`) | ✅ new endpoint |

All business logic is in the service layer (`account_service`, `address_service`, `user_service`). The routers only translate service errors into HTTP responses.

### Deactivation rules and how they are enforced

| Rule | Enforcement | Test |
| --- | --- | --- |
| Deactivate the User Service profile only | `account_service.deactivate_account` sets `user_profiles.is_active = false` and nothing else | `test_deactivate_account` |
| Do not delete or silently modify the Authentication Service account | No code path sends anything to the Authentication Service except the read-only verify-token call. The response says `"authentication_account_changed": false` | `test_deactivation_does_not_call_the_authentication_service` |
| Inactive profile cannot manage addresses or profile | Every service function goes through `user_service.get_active_profile`, which raises `ProfileDeactivatedError` (403) | `test_inactive_profile_cannot_do_anything`: 15 operations × both ways of deactivating = 30 cases |
| Preserve records | Profile row, all fields, all addresses and the default flag are kept | `test_deactivation_preserves_addresses_and_the_default` |

### Default-address rules and how they are enforced

| Rule | Enforcement | Test |
| --- | --- | --- |
| Only one default per profile | Service clears the old default before setting a new one, under the profile lock; unique key `uq_user_addresses_one_default_per_user` in MySQL | `test_switching_default_repeatedly_always_leaves_exactly_one`, concurrency check |
| No stale default after deleting the default | The delete and the choice of a new default happen in one transaction. The deleted row is gone, so it cannot be the default | `test_deleting_the_default_leaves_no_stale_default`, `test_deleting_the_only_address_leaves_no_default` |
| Automatic choice of another address | **Implemented and documented**: the oldest remaining address becomes the default. Deleting the only address leaves no default, and `GET .../default` returns 404 | `test_deleting_the_default_makes_the_oldest_remaining_address_default` |

## Test results

Full output: [`Test_Results/day2_pytest_sqlite.txt`](Test_Results/day2_pytest_sqlite.txt), [`Test_Results/day2_pytest_mysql.txt`](Test_Results/day2_pytest_mysql.txt).

| Command | Database | Result |
| --- | --- | --- |
| `pytest -v` | SQLite in memory | **360 passed** |
| `USER_SERVICE_TEST_DB=mysql pytest -v` | `shopease_user_db` in `user-mysql`, at head `4f1a9d27c5e3`; each test rolled back (0 rows left afterwards) | **360 passed** |
| Manual API tests (see 07) | | Not run yet at that point. Later replaced by the scripted live audit and the Newman run (below) |
| `docker compose ps` | | Only `user-mysql` running (healthy) at that point; full stack run later (below) |

The table above was the state at the end of the address and account work. Final results at the end of Day 2:

| Command | Result | Output |
| --- | --- | --- |
| `pytest -v` (SQLite) | **518 passed**, 1 warning (third-party deprecation) | [`final_pytest_sqlite.txt`](Test_Results/final_pytest_sqlite.txt) |
| `USER_SERVICE_TEST_DB=mysql pytest -v` | **518 passed**, 1 warning | [`final_pytest_mysql.txt`](Test_Results/final_pytest_mysql.txt) |
| `python scripts/live_api_audit.py` (Docker, real tokens) | **73 passed, 0 failed** | [`final_live_api_audit.txt`](Test_Results/final_live_api_audit.txt) |
| `newman run postman/...collection.json` | 28 requests, **38 assertions, 0 failed** | [`postman_newman_run.txt`](Test_Results/postman_newman_run.txt) |
| `docker compose config`, `ps`, Alembic in the container | Valid; both healthy; at head `4f1a9d27c5e3`; `alembic check` clean | [`final_validation_checks.txt`](Test_Results/final_validation_checks.txt) |

The 518 tests: address 125, account 67, profile 87, token integration 57, database layer 17, startup and settings 15 (7 plus the 8 `API_PREFIX` tests added during the Docker work), and security audit 150.

| Test file | Tests | Covers |
| --- | --- | --- |
| `test_address_api.py` | 125 | All 6 address endpoints: token and profile required, 403 when deactivated, validation (28 invalid values), ownership (4 kinds of access to another user's address), default rules, profile lock requested by every write, rollback when commit fails |
| `test_account_api.py` | 67 | Account endpoints and `GET .../default`: token required, inactive auth account, account before and after profile creation, contact update and its validation (email rejected), deactivation policy, 30 operations refused after deactivation, no call to the Authentication Service, no stale default |
| `test_user_profile_api.py` | 87 | Profile endpoints (Day 1) |
| `test_auth_integration.py` | 57 | Verify-token integration (Day 1) |
| `test_database_layer.py` | 17 | Models and sessions (Day 1) |
| `test_scaffold.py` | 7 | Startup and settings (Day 1) |

**Fault checks.** Each bug below was put into the code on purpose, one at a time. The tests caught every one, and the files were then restored:

| Deliberate bug | Failing tests |
| --- | --- |
| Address lookup not filtered by owner | 4 |
| Old default not cleared when setting a new one | 5 |
| No new default chosen after deleting the default | 1 (address), 1 (account) |
| No rollback on failure | 3 |
| Profile row not locked | 4 |
| Default-address lookup not filtered by owner | 1 |
| Account deactivation doing nothing | 17 |
| Contact update also changing `full_name` | 1 |

## Issues and decisions

| Issue / decision | Resolution |
| --- | --- |
| Address types were `HOME`, `WORK`, `OTHER`; the requirement is Home, Office, Other | New migration `4f1a9d27c5e3`, written by hand because autogenerate does not compare CHECK constraints. Existing `WORK` rows are converted, and the downgrade converts them back |
| Address type spelling | Exact upper case (`HOME`, `OFFICE`, `OTHER`), the same rule as `gender` |
| Address paths | `/api/users/addresses` instead of the planned `/api/users/me/addresses` |
| How to stop two concurrent requests from creating two defaults | Lock the owning profile row in every address write. Without the lock, the live check had 219 of 300 requests fail (unique-key errors and deadlocks); with it, none failed |
| Deleting the default address | The oldest remaining address becomes the default, in the same transaction. Kept as documented behaviour so checkout always has a default while addresses exist |
| `GET /addresses/default` matched by `/{address_id}` | The `/default` route is declared first |
| Planned admin route `/api/users/{auth_user_id}` would match `/addresses` and `/account` | Address and account routers are registered before the profile router |
| Two deactivation endpoints | `PATCH /api/users/account/deactivate` (requested) and `DELETE /api/users/profile` (Day 1) share one service function and behave the same |
| Contact information | Phone number only. Email is the login identity and belongs to the Authentication Service, so it is rejected with 422 |
| `GET /api/users/account` before a profile exists | 200 with `profile: null` and `profile_status: NOT_CREATED`, so a new user can see their account |
| PUT on an address | Full replacement like profile PUT. `is_default` is not accepted there; use `PATCH .../default` |
| DELETE responses | 200 with a message, matching profile DELETE |

## Remaining work

| Item | Status |
| --- | --- |
| Admin endpoints: list, read, reactivate (ADMIN only) | **Not implemented** |
| Screenshots (`screenshots/`, 20 listed) | **Done**: 20 of 20 plus 5 extra (including cross-user access denial), captured live on 11 November 2026; see [screenshots/README.md](screenshots/README.md) |
| Manual walkthrough in Swagger UI | Not recorded. The same scenarios were run as scripted HTTP calls and with Newman |
| Live test of a real token after its 30-minute expiry, and of an account deactivated in the Authentication Service | Not run live; covered by automated tests only |
| Audit findings 2 (no address limit) and 3 (no rate limiting) | Open |
| Posting the Teams updates | Text ready in [10](10_Teams_Progress_Updates.md) |
