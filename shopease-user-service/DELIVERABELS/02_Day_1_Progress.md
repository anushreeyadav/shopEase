# 02 – Day 1 Progress

| | |
| --- | --- |
| Date | 10 November 2026 |
| Goal | Foundation, database, JWT integration, profile API |
| Status | **Profile module complete.** The live test with the real Authentication Service, open at the end of Day 1, was done on Day 2 (see [06, section 6](06_JWT_Integration_Report.md#6-live-test-against-the-running-authentication-service)) |

## Completed

| Item | Evidence |
| --- | --- |
| Project structure (routers, models, schemas, services, core, database, alembic, tests) | Project tree |
| Dependencies pinned, installed in a clean Python 3.11 `.venv`, `pip check` clean. No JWT or password packages | `requirements.txt` |
| Pydantic Settings for MySQL and the Authentication Service, read from the environment or `.env`; placeholder passwords rejected; secrets masked | `app/core/config.py`, `.env.example` |
| Database layer: engine, `SessionLocal`, `Base`, `get_db()` with rollback on error; database errors return 503 | `app/database/connection.py`, `app/exception_handlers.py` |
| `UserProfile` and `UserAddress` models: one-to-many, FK with ON DELETE CASCADE, one default address per user, local `is_active` | `app/models/`, [05](05_Database_Schema.md) |
| Alembic configured; initial migration `8c2e3b6d4acf` generated, applied, downgraded and re-applied against `shopease_user_db` | `alembic/`, [05](05_Database_Schema.md#migrations) |
| Authentication through `POST /api/auth/verify-token`: `get_current_authenticated_user()`, fails closed (401, 403, 503), token never logged | `app/core/security.py`, [06](06_JWT_Integration_Report.md) |
| **Profile API**: `POST`, `GET`, `PUT`, `PATCH`, `DELETE` `/api/users/profile` | `app/routers/user_routes.py`, `app/services/user_service.py`, `app/schemas/user_schema.py`, [04](04_API_Documentation.md#user-profile-endpoints) |
| Validation of full name, phone, date of birth, gender, profile image; error format shared with the Authentication Service, without echoing values | `app/schemas/user_schema.py`, `app/exception_handlers.py` |
| Deactivation: DELETE sets `is_active=false`, keeps the record, does not touch the auth account; later operations get 403 (extended on Day 2: see below) | `user_service.deactivate_profile` |
| Deliverables folder and documents | `DELIVERABELS/` |

### Profile module: identity rules and how they are enforced

| Rule | Enforcement | Test |
| --- | --- | --- |
| `auth_user_id` only from the verified identity | Every route passes `user.auth_user_id` from `get_current_authenticated_user` | `test_auth_user_id_in_the_query_is_ignored` |
| Never accepted from the body | `extra="forbid"` on every request schema: 422 | `test_identity_and_credential_fields_are_rejected_in_the_body` (6 fields) |
| No selecting another profile ID | No endpoint takes a profile or user ID | `test_users_only_see_their_own_profile`, `test_patch_only_affects_the_callers_profile` |
| No duplicate profiles | Check before insert, plus the unique constraint; a lost race returns 409 | `test_duplicate_profile_is_rejected`, `test_duplicate_created_concurrently_is_reported_as_409` |
| Every query scoped to the caller | All service queries filter `UserProfile.auth_user_id == auth_user_id`; updates lock that row | Fault test: removing the filter makes 3 tests fail |

## Test results

Full output: [`Test_Results/day1_pytest_sqlite.txt`](Test_Results/day1_pytest_sqlite.txt), [`Test_Results/day1_pytest_mysql.txt`](Test_Results/day1_pytest_mysql.txt).

| Command | Database | Result |
| --- | --- | --- |
| `pytest -v` | SQLite in memory | **168 passed** |
| `USER_SERVICE_TEST_DB=mysql pytest -v` | `shopease_user_db` in `user-mysql`, at Alembic head; each test rolled back (0 rows left afterwards) | **168 passed** |

| Test file | Tests | Covers |
| --- | --- | --- |
| `test_user_profile_api.py` | 87 | All 5 profile endpoints: token required (missing token, rejected token), create, read, full update, partial update, deactivate, 403 after deactivation for all 5 methods, validation (27 invalid values, valid boundaries, images, genders), identity spoofing, scoping between two users, duplicate race |
| `test_auth_integration.py` | 57 | Verify-token integration with mocked responses (see 06) |
| `test_database_layer.py` | 17 | Phone normalization, model constraints, `get_db` rollback |
| `test_scaffold.py` | 7 | Startup, health, settings, no JWT secret |

**Fault check:** three deliberate bugs were put into `user_service.py` one at a time, and the profile tests caught each one:
- Deactivation not setting `is_active`: 6 failures.
- PUT keeping omitted fields: 1 failure.
- Queries not scoped to the caller: 3 failures.

The file was then restored, and all 168 tests pass.

## Issues and decisions

| Issue / decision | Resolution |
| --- | --- |
| Port clash with the Authentication Service's MySQL (3308) | The User Service's MySQL uses host port 3309 |
| Profiles cannot use a foreign key to `users` in another database | `auth_user_id` is stored as a unique integer: the `user.id` returned by verify-token |
| How to check tokens: copy the JWT secret, or call the Authentication Service | Call `verify-token`. No signing secret in this service, and deactivated users are rejected at once (see 06) |
| MySQL rejected `ON DELETE CASCADE` on a column used by a stored generated column | The one-default marker reads only `is_default` (see 05) |
| Alembic's database guard left a transaction open, so a downgrade was not recorded | Fixed in `env.py`; cycle rerun (see 05) |
| What DELETE on a profile should do | Deactivate locally (`is_active=false`), keep the record, leave the auth account alone |
| What a deactivated profile may do | Every operation, POST included, returns 403 `User profile is deactivated`. Reactivation is reserved for a planned admin endpoint |
| PUT vs PATCH | PUT replaces all fields (omitted optional fields become null); PATCH changes only the fields sent, and an empty PATCH is rejected |
| Allowed `profile_image` values | An http(s) URL with a host and no credentials, or a safe server path ending in an image extension (see 04) |
| Validation error format | Same as the Authentication Service: `{"detail": "Validation failed", "errors": [{field, message}]}`, without echoing input |

## Day 1 work changed on Day 2 (11 November 2026)

The account-management review on Day 2 extended some Day 1 behaviour. The Day 1 tests above still pass unchanged.

| Change | Detail |
| --- | --- |
| Second way to deactivate | `PATCH /api/users/account/deactivate` calls the same `user_service.deactivate_profile` as `DELETE /api/users/profile`. Both remain supported |
| Deactivation now also blocks addresses and the account endpoints | A deactivated profile gets 403 on every profile, address and account endpoint. Records, including addresses and the default address, are kept |
| Contact update | `PATCH /api/users/account/contact` changes only `phone_number`, through `user_service.update_profile`. Email stays with the Authentication Service |
| `get_active_profile` made public | The address and account services reuse the Day 1 profile lookup instead of copying it, so every module applies the same active-profile rule |
| Status documentation | The difference between the Authentication Service account status and the local profile status is now documented in [04](04_API_Documentation.md#authentication-account-status-vs-user-service-profile-status) |

Details and test results: [03_Day_2_Progress.md](03_Day_2_Progress.md).

## Open at the end of Day 1, and what happened

| Item | Outcome |
| --- | --- |
| Live test with a real token from the running Authentication Service | **Done on Day 2** (11 November 2026), against the Docker containers: real tokens accepted, a tampered or missing token 401, and the Authentication Service stopped 503. See [06, section 6](06_JWT_Integration_Report.md#6-live-test-against-the-running-authentication-service) |
| Day 1 Teams update | Text ready in [10](10_Teams_Progress_Updates.md). Posting it is up to the author |
| Admin endpoints (list, read, reactivate) | **Not implemented.** Still open at the end of Day 2 (see [09](09_Final_Completion_Report.md)) |

## Plan for Day 2

Address API, Docker run of the full stack, live API testing and screenshots, and the remaining documents.
