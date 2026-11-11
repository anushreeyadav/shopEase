# Development Checklist – Two-Day Task

Tick an item only after it is done **and** checked. Record evidence (test output, screenshots) as you go, not at the end.

## Day 1 – Foundation, database, profile API

### Setup
- [x] Create the project structure (`app/routers`, `models`, `schemas`, `services`, `core`, `database`, `alembic/versions`, `tests`)
- [x] Create `config.py`, `security.py`, `connection.py`, `main.py`
- [x] Create `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `alembic.ini`, `.env.example`, `.gitignore`, `.dockerignore`
- [x] Create `.env` from `.env.example` (MySQL settings, `AUTH_SERVICE_VERIFY_URL`, `AUTH_SERVICE_TIMEOUT_SECONDS`)
- [x] Create the DELIVERABELS folder and documents
- [x] Create a Python 3.11 virtual environment and `pip install -r requirements.txt`; `pip check` clean
- [x] `pytest -v`: foundation tests pass

### Database
- [x] `get_db()` with rollback on error and guaranteed close; database errors return 503
- [x] `UserProfile` model (`user_profiles`: gender, profile_image, local `is_active`, no credentials)
- [x] `UserAddress` model (`user_addresses`, FK to `user_profiles` with ON DELETE CASCADE, one default per user)
- [x] Phone number normalization in schemas and models
- [x] `docker compose up -d user-mysql`, then check it is healthy
- [x] Configure `alembic.ini` (no URL or credentials) and `alembic/env.py` (settings from the environment, explicit model imports, type and default comparison, wrong-database guard)
- [x] `alembic revision --autogenerate -m "create user and address tables"` (revision `8c2e3b6d4acf`)
- [x] Review the generated migration by hand
- [x] `alembic upgrade head`, then `DESCRIBE` both tables in MySQL
- [x] `alembic downgrade -1` removes every created object; an unrelated database with same-named tables is untouched
- [x] `alembic check` clean
- [x] Live constraint test (15/15)
- [x] Update [05_Database_Schema.md](05_Database_Schema.md) with the real `DESCRIBE` output

### JWT integration
- [x] `get_current_authenticated_user` dependency calls `POST /api/auth/verify-token` on the Authentication Service
- [x] Automated tests with mocked verification responses (missing, invalid, expired, inactive, malformed, unavailable)
- [x] `require_admin` dependency
- [x] Start the Authentication Service, register and log in, and copy a real token (Day 2, Docker)
- [x] Call a protected User Service endpoint with that token: 200
- [x] No token and a wrong (tampered or malformed) token: 401. A real **expired** token was not tested live; it is covered by automated tests only
- [x] Authentication Service stopped: 503

### Profile API
- [x] Implement `user_service`: create, get, replace, update, deactivate (every query scoped to the caller)
- [x] `POST /api/users/profile` (201, and 409 if the profile exists)
- [x] `GET /api/users/profile` (200, and 404 if there is no profile)
- [x] `PUT /api/users/profile` (200, full replacement)
- [x] `PATCH /api/users/profile` (200, partial update)
- [x] `DELETE /api/users/profile` (200, deactivates: `is_active=false`, record kept, auth account untouched)
- [x] 403 `User profile is deactivated` for every operation after deactivation
- [x] Tests for every profile endpoint, including 401, 403, 404, 409, and 422 (87 tests, SQLite and MySQL)
- [x] Update 02_Day_1_Progress.md and 04_API_Documentation.md
- [ ] Post the Day 1 Teams update (text ready in 10; posting is up to the author)
- [ ] Admin endpoints: list, read, reactivate (ADMIN only: 403 for USER). **Not implemented**

## Day 2 – Address API, Docker, testing, documents

### Address API
- [x] Implement `address_service`, with every query filtered by the caller's profile
- [x] Address types `HOME`, `OFFICE`, `OTHER` (migration `4f1a9d27c5e3`, upgrade and downgrade verified on MySQL)
- [x] `GET /api/users/addresses` (default first)
- [x] `POST /api/users/addresses` (the first address becomes the default)
- [x] `GET /api/users/addresses/{id}` (404 for another user's address, identical to a missing one)
- [x] `PUT /api/users/addresses/{id}` (full replacement)
- [x] `DELETE /api/users/addresses/{id}` (if it was the default, promote the oldest remaining address)
- [x] `PATCH /api/users/addresses/{id}/default` (exactly one default afterwards)
- [x] One transaction per write, owning profile row locked (`FOR UPDATE`), rollback on failure
- [x] Tests, including one user trying to reach another user's address (125 tests, SQLite and MySQL)
- [x] Live concurrency check on MySQL: 300 concurrent default changes, exactly 1 default
- [x] Update 04_API_Documentation.md and 05_Database_Schema.md

### Account management
- [x] `GET /api/users/account` (authentication account and profile)
- [x] `PATCH /api/users/account/contact` (phone only; email stays with the Authentication Service)
- [x] `PATCH /api/users/account/deactivate` (local profile only, records kept, no call to the Authentication Service)
- [x] `GET /api/users/addresses/default`
- [x] Inactive profile refused on every profile, address and account operation
- [x] Tests (67, SQLite and MySQL); 02, 03 and 04 updated

### Docker
- [x] `docker compose up -d --build --wait`: both containers healthy
- [x] Migrations ran automatically on container start (check the logs), also on a new empty volume
- [x] Full flow against the container: auth login (8001), then user-service calls (8002). Live audit 73/73
- [x] `docker compose down` and `up` again: the data is still there (volume)

### Testing and evidence
- [x] `pytest -v` all passing; save the output to `Test_Results/` (360 passed, SQLite and MySQL)
- [x] API test pass against the running services, recorded in 07: Postman collection run with Newman (38/38), plus the scripted live audit (73/73). A walkthrough by hand in Swagger UI was not recorded
- [x] Capture every screenshot listed in [screenshots/README.md](screenshots/README.md) (20 of 20, plus 5 extra, on 11 November 2026)
- [x] Check that no screenshot shows a whole token, a password, or `.env` contents (checked in the page before each capture, and each image reviewed)

### Documents
- [x] 03 Day 2 progress (updated after the Docker and live tests)
- [x] 04 API documentation: real behaviour for all 15 endpoints; admin endpoints stay marked as planned
- [x] 06 JWT integration report: add the real test results
- [x] 07 API testing report, 08 Docker execution report
- [x] 09 Final completion report
- [x] 10 Teams updates (Day 1 and Day 2)
- [x] Word versions in `Word_Documents/` (4 documents)
- [x] Final check: `shopease-auth-service` and `shopease-product-service` unchanged; nothing committed or pushed
