# ShopEase User Service

User profiles and saved addresses for the ShopEase e-commerce platform. This is an independent FastAPI microservice with its own MySQL database. Callers authenticate with access tokens from the [ShopEase Authentication Service](../shopease-auth-service/README.md), which also checks every token.

> **Status (11 November 2026):** the profile, address and account APIs, JWT verification through the Authentication Service, the Alembic migrations and the Docker setup are implemented and verified:
> - **Automated tests:** 518 pass on SQLite and on MySQL.
> - **Live audit:** 73 of 73 checks pass against the Docker containers, using real tokens.
> - **Postman collection:** passes when run with Newman.
>
> Still open:
> - **Admin endpoints:** not implemented.
> - **Screenshots:** 20 of 20 required, plus 5 extra (including cross-user access denial), captured from the running system (`DELIVERABELS/screenshots/`).
>
> Details are in [Known limitations](#known-limitations) and the [final completion report](DELIVERABELS/09_Final_Completion_Report.md).

## Overview

| | |
| --- | --- |
| What it stores | A customer's **profile** (full name, phone, date of birth, gender, profile image URL) and **saved addresses** (Home, Office, Other), with exactly one default address once any exist |
| What it does not do | Register users, log them in, store passwords, or sign or decode JWTs. Those belong to the Authentication Service |
| Port | API on **8002**. Its MySQL database `shopease_user_db` is reachable only inside Docker, or on `127.0.0.1:3309` with the dev override |
| Identity | Always the user returned by the Authentication Service for the caller's token. Never an ID sent by the client |

## Architecture

```
 Client (Swagger UI, Postman, another service)
   |  1. POST /api/auth/login  ------------------->  Authentication Service  :8001   (separate project)
   |  <- access_token (JWT)                         owns: email, password hash, role, is_active
   |                                                        ^
   |  2. GET /api/users/...  Authorization: Bearer <token>  |  3. POST /api/auth/verify-token
   v                                                        |     (same Authorization header)
 User Service  :8002  ---------------------------------------+     <- 200 {valid, user{id, role, ...}} / 401 / 403
   routers  ->  services  ->  SQLAlchemy models
   |
   v
 MySQL 8.4  shopease_user_db   (container user-mysql, named volume user_mysql_data)
   user_profiles   (auth_user_id UNIQUE, local is_active)
   user_addresses  (FK user_id -> user_profiles.id, one default per profile)
```

- **Layers:**
  - `routers/` handle HTTP only: path and body validation, and mapping status codes.
  - `services/` hold the business rules: ownership, default address, deactivation and transactions.
  - `models/` define the tables.
  - `schemas/` are the Pydantic request and response models, with `extra="forbid"`, so a client cannot send `auth_user_id`, `user_id` or `id`.
- **Token verification:**
  - `app/core/security.py` sends the caller's `Authorization` header to `AUTH_SERVICE_VERIFY_URL` and uses only the returned `user.id`.
  - The service holds no JWT secret.
  - A 401 or 403 from the Authentication Service is passed on.
  - If that service is down, or returns an unexpected response, the request fails with 503. The token is never trusted without the check.
- **Database link:** `user_profiles.auth_user_id` stores the Authentication Service's user ID. There is no cross-database foreign key, because each service owns its own database.
- **Two statuses:**
  - **Authentication account status** (active or inactive in the Authentication Service) decides whether a token is accepted.
  - **Profile status** (`user_profiles.is_active`) is local. Deactivating it never changes the Authentication Service account.

## Technology stack

| Area | Choice |
| --- | --- |
| Language | Python 3.11 |
| Web framework | FastAPI 0.162, Uvicorn 0.54 |
| Database | MySQL 8.4 (Docker image `mysql:8.4`) |
| ORM and migrations | SQLAlchemy 2.1, PyMySQL 1.2, Alembic 1.20 |
| Validation and settings | Pydantic 2.14, pydantic-settings 2.16 |
| Calls to the Authentication Service | HTTPX 0.28 |
| Containers | Docker, Docker Compose (tested with Docker Engine 29.6.2, Compose v5.3.1) |
| Tests | pytest 9.2, FastAPI TestClient; Postman collection run with Newman 6.2.1 |

Exact versions are pinned in [requirements.txt](requirements.txt). The service has no JWT or password-hashing libraries.

## Folder structure

```
shopease-user-service/
  app/
    main.py                  FastAPI app, router registration, /, /health, /health/db
    exception_handlers.py    validation, database (503) and unexpected (500) errors, no internal details
    core/
      config.py              settings from environment variables and .env (Pydantic Settings)
      security.py            token verification through the Authentication Service, require_admin
      phone_utils.py         phone number normalization
    database/connection.py   engine, session (get_db), declarative Base
    models/                  user_model.py (user_profiles), address_model.py (user_addresses)
    schemas/                 user_schema.py, address_schema.py, account_schema.py
    services/                user_service.py, address_service.py, account_service.py
    routers/                 user_routes.py, address_routes.py, account_routes.py
  alembic/                   env.py and versions/ (8c2e3b6d4acf, 4f1a9d27c5e3)
  tests/                     pytest suite (518 tests) and fake_auth_service.py
  scripts/live_api_audit.py  live check of every endpoint against running services
  postman/                   Postman collection and the script that generates it
  DELIVERABELS/              reports 01-10, Test_Results/, screenshots/, Word_Documents/
  Dockerfile, docker-compose.yml, docker-compose.dev.yml, .dockerignore
  alembic.ini, pytest.ini, requirements.txt, .env.example, .gitignore
```

## Environment setup

Requires Python 3.11 and Docker Desktop.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Open `.env` and replace each `change-me` value with a generated password:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `MYSQL_DATABASE` | | `shopease_user_db` | Database name |
| `MYSQL_USER` | **yes** | – | Database user |
| `MYSQL_PASSWORD` | **yes** | – | Database password. A `change-me` placeholder stops startup |
| `MYSQL_HOST` | | `127.0.0.1` | Database host (Compose sets `user-mysql` in the container) |
| `MYSQL_PORT` | | `3309` | Database port (Compose sets `3306` in the container) |
| `MYSQL_ROOT_PASSWORD` | Docker only | – | Root password for the MySQL container |
| `AUTH_SERVICE_VERIFY_URL` | | `http://127.0.0.1:8001/api/auth/verify-token` | Verify endpoint, used when Uvicorn runs on this machine |
| `DOCKER_AUTH_SERVICE_VERIFY_URL` | | `http://host.docker.internal:8001/api/auth/verify-token` | The same endpoint, as the container reaches it |
| `AUTH_SERVICE_TIMEOUT_SECONDS` | | `5` | Timeout per verify call (more than 0, at most 30) |
| `APP_NAME`, `APP_VERSION`, `APP_ENV`, `LOG_LEVEL`, `API_PREFIX`, `DOCS_ENABLED` | | see `.env.example` | General settings. `API_PREFIX` must look like `/api` |
| `USER_SERVICE_HOST_PORT` | | `8002` | Host port for the container |

How secrets are protected:

- **Git and the image:** `.env` is listed in `.gitignore` and `.dockerignore`, so it is never committed or copied into the image.
- **Masking:** the database password is a `SecretStr`, and is masked in `repr()` and in the connection URL.
- **Startup errors:** a rejected setting is never echoed (`hide_input_in_errors`).
- **Database errors:** SQL parameters are hidden (`hide_parameters`), and failures are logged by exception class only.
- **Tokens:** the caller's token is sent only to `AUTH_SERVICE_VERIFY_URL`. It is never logged or returned, and redirects are not followed.

## Database configuration

| | |
| --- | --- |
| Database | `shopease_user_db`, MySQL 8.4, `utf8mb4` / `utf8mb4_0900_ai_ci` (the server default) |
| Tables | `user_profiles` (one per Authentication Service user, `auth_user_id` unique), `user_addresses` (foreign key `user_id` → `user_profiles.id`, ON DELETE CASCADE) |
| One default address per profile | A unique key on a generated `default_marker` column, and every address write locks the owning profile row (`SELECT ... FOR UPDATE`) |
| In Docker | Container `user-mysql`, named volume `user_mysql_data`, no published port. The service connects to `user-mysql:3306` |
| On this machine | `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d user-mysql` publishes it on `127.0.0.1:3309` |
| Guard | [alembic/env.py](alembic/env.py) refuses to run against any database other than `shopease_user_db` |

Columns, constraints and the real `DESCRIBE` output: [05_Database_Schema.md](DELIVERABELS/05_Database_Schema.md).

## Authentication integration

Every `/api/users/...` endpoint uses the dependency `get_current_authenticated_user()` in [app/core/security.py](app/core/security.py):

| Authentication Service answer | User Service response |
| --- | --- |
| 200 `{valid: true, user{id, ...}}` | The request continues as `user.id` |
| 401 (missing, invalid, tampered or expired token) | 401 `Could not validate credentials` |
| 403 (account inactive in the Authentication Service) | 403 `Inactive user` |
| Timeout, connection error, 5xx, redirect, malformed body | 503 `Authentication service unavailable` |

| User Service runs | `AUTH_SERVICE_VERIFY_URL` |
| --- | --- |
| Uvicorn on this machine | `http://127.0.0.1:8001/api/auth/verify-token` (default) |
| In its Docker container | `http://host.docker.internal:8001/api/auth/verify-token`. The Authentication Service is a separate Compose project, so its container name does not resolve here |

Check that the endpoint is reachable. A `401` without a token means it is:

```powershell
curl.exe -s -o NUL -w "%{http_code}" -X POST http://127.0.0.1:8001/api/auth/verify-token
```

Full report: [06_JWT_Integration_Report.md](DELIVERABELS/06_JWT_Integration_Report.md).

## API documentation

All `/api/users/...` endpoints need `Authorization: Bearer <token>`, and act only on the caller's own data.

| Method | Path | Purpose | Success |
| --- | --- | --- | --- |
| GET | `/`, `/health`, `/health/db` | Service info, liveness, database connection (no token) | 200 |
| POST | `/api/users/profile` | Create the caller's profile | 201 (409 if it exists) |
| GET | `/api/users/profile` | Read it | 200 |
| PUT | `/api/users/profile` | Replace it | 200 |
| PATCH | `/api/users/profile` | Update some fields | 200 |
| DELETE | `/api/users/profile` | Deactivate it (same as `PATCH /account/deactivate`) | 200 |
| GET | `/api/users/account` | Authentication account and profile together | 200 |
| PATCH | `/api/users/account/contact` | Change the phone number | 200 |
| PATCH | `/api/users/account/deactivate` | Deactivate the local profile only. Records are kept | 200 |
| POST | `/api/users/addresses` | Add an address. The first one becomes the default | 201 |
| GET | `/api/users/addresses` | List them, default first | 200 |
| GET | `/api/users/addresses/default` | The default address | 200 (404 if none) |
| GET | `/api/users/addresses/{address_id}` | One address | 200 |
| PUT | `/api/users/addresses/{address_id}` | Replace it | 200 |
| DELETE | `/api/users/addresses/{address_id}` | Delete it. If it was the default, the oldest remaining one becomes the default | 200 |
| PATCH | `/api/users/addresses/{address_id}/default` | Make it the default | 200 |

Common errors:
- **401:** no valid token.
- **403:** the profile is deactivated, or the account is inactive in the Authentication Service.
- **404:** no profile; or the address is missing **or belongs to another user**, with the same response in both cases.
- **409:** the profile already exists.
- **422:** validation failed. The response names the field, never the value.
- **503:** a dependency is unavailable.

Full contract, field rules and examples: [04_API_Documentation.md](DELIVERABELS/04_API_Documentation.md).

## Alembic commands

Tables are created only by Alembic migrations, never by `create_all()`. Alembic reads the same `MYSQL_*` settings as the app, and `alembic.ini` contains no URL or credentials. On this machine, first start MySQL with its development port: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d user-mysql`.

```powershell
alembic upgrade head          # apply all migrations
alembic downgrade -1          # undo the most recent migration
alembic current               # revision applied to the database
alembic history               # all migrations
alembic check                 # fails if the models and the database differ
alembic revision --autogenerate -m "describe the change"   # new migration; always review it
```

| Revision | Description |
| --- | --- |
| `8c2e3b6d4acf` | Creates `user_profiles` and `user_addresses`, the unique `auth_user_id`, the foreign key with ON DELETE CASCADE, and the indexes |
| `4f1a9d27c5e3` (head) | Address types become `HOME`, `OFFICE`, `OTHER`. Existing `WORK` rows are converted |

In Docker, the container runs `alembic upgrade head` before starting Uvicorn. Inside the running container: `docker compose exec user-service alembic current`.

## Docker commands

Start the Authentication Service first, in its own folder (`docker compose up -d --wait`, port 8001). Then, from this folder, **in PowerShell or cmd**:

```powershell
docker compose config                  # check the configuration
docker compose up --build -d --wait    # build; start MySQL; wait until healthy; migrate; start the API
docker compose ps                      # both containers should be "healthy"
docker compose logs -f user-service    # Alembic lines, then "Uvicorn running on http://0.0.0.0:8002"
docker compose down                    # stop (add -v to also delete the database volume)
```

| Container | Reachable from | Notes |
| --- | --- | --- |
| `user-service` | `http://127.0.0.1:8002` (this machine only) | Runs as an unprivileged user. Starts only after `user-mysql` is healthy, and accepts requests only after the migrations succeed |
| `user-mysql` | `user-service` only, as `user-mysql:3306` | Not published. Data in the named volume `user_mysql_data` |

- **MySQL from this machine** (Alembic, MySQL-mode tests): add `-f docker-compose.yml -f docker-compose.dev.yml`.
- **Do not run Compose from Git Bash with variables exported from `.env`.** Git Bash rewrites `/api` into a Windows path, and an exported variable takes priority over `.env`. `API_PREFIX` is validated, so the service then stops with a clear error.

Execution report: [08_Docker_Execution_Report.md](DELIVERABELS/08_Docker_Execution_Report.md).

## Swagger instructions

1. Start both services (see [Docker commands](#docker-commands)).
2. Get a token from the Authentication Service. Open http://127.0.0.1:8001/docs, run `POST /api/auth/register` with a test user, then `POST /api/auth/login`, and copy `access_token` from the response.
3. Open the User Service Swagger UI at **http://127.0.0.1:8002/docs** (ReDoc: `/redoc`).
4. Click **Authorize**, paste the token without the word `Bearer`, and click **Authorize** again.
5. Run the requests in this order:
   - `POST /api/users/profile`
   - `GET /api/users/account`
   - `POST /api/users/addresses` (twice)
   - `GET /api/users/addresses`
   - `PATCH /api/users/addresses/{address_id}/default`
   - `GET /api/users/addresses/default`
   - Finally, `PATCH /api/users/account/deactivate`. After it, the profile and address endpoints return 403.
6. Tokens expire after 30 minutes (the Authentication Service default). After that, log in again and reauthorize.

Swagger UI shows the token in its `curl` box. Crop or collapse it before taking a screenshot. Set `DOCS_ENABLED=false` to turn off `/docs` and `/redoc` in production.

## Postman testing

[postman/ShopEase_User_Service.postman_collection.json](postman/ShopEase_User_Service.postman_collection.json) has 28 requests, each with test assertions.

[postman/ShopEase_User_Service.postman_environment.json](postman/ShopEase_User_Service.postman_environment.json) is the environment template. It holds only `userBaseUrl` and `authBaseUrl`, with no credentials. Do not add `email`, `password` or `token` to it: an environment value overrides the collection variable of the same name, so an empty one would hide the value the collection sets during the run.

| Folder | Requests |
| --- | --- |
| 0 Health | Service health, database health |
| 1 Authentication Service (8001) | Register a generated test user, log in (stores the token), verify the token |
| 2 Authentication failures | A call without a token gets 401 |
| 3 Profile | Create; create again (409); create with a client-supplied `auth_user_id` (422); get; PUT; PATCH |
| 4 Account | Get the account, update the contact phone |
| 5 Addresses | Create two addresses, list, get, PUT, set the default, get the default, delete the default (the remaining address is promoted), get the deleted one (404) |
| 6 Deactivation (run last) | Deactivate, then profile and addresses return 403, while login on the Authentication Service still works |

**In Postman:** Import both files, select the **ShopEase User Service - local** environment, and run the whole collection with **Run collection**. The base URLs are the collection variables `userBaseUrl` and `authBaseUrl`. The test email and password are generated on the first run, and the token is stored in the `token` variable. Clear `token` and `password` before exporting or sharing the collection.

**From the command line (Newman):**

```powershell
npx newman@6.2.1 run postman\ShopEase_User_Service.postman_collection.json -e postman\ShopEase_User_Service.postman_environment.json
```

Result on 11 November 2026: 28 requests and 38 assertions, 0 failed ([postman_newman_run.txt](DELIVERABELS/Test_Results/postman_newman_run.txt)); with the environment template, also 38/38 ([postman_newman_run_with_environment.txt](DELIVERABELS/Test_Results/postman_newman_run_with_environment.txt)). Copies of both Postman files are in `DELIVERABELS/Test_Results/`. To change the collection, edit and run `python postman/gen_collection.py`.

## Tests

```powershell
pytest -v                                                                  # SQLite in memory
$env:USER_SERVICE_TEST_DB = "mysql"; pytest -v; Remove-Item Env:USER_SERVICE_TEST_DB   # real shopease_user_db
python scripts/live_api_audit.py                                           # live, against running services
```

- **pytest:**
  - The Authentication Service is replaced by a fake HTTP transport that signs and checks real JWTs, so the real service does not need to be running.
  - Each test runs inside a transaction that is rolled back.
  - MySQL mode needs `user-mysql` started with `docker-compose.dev.yml`, after `alembic upgrade head`.
  - **Result:** 518 passed on SQLite and on MySQL.
- **Live audit:**
  - Registers two new users on the running Authentication Service.
  - Calls every endpoint, tries cross-user access, and deactivates one profile.
  - **Result:** 73 of 73 checks passed.

Results and reports: [07_API_Testing_Report.md](DELIVERABELS/07_API_Testing_Report.md), [DELIVERABELS/Test_Results/](DELIVERABELS/Test_Results/).

## Known limitations

- **Admin endpoints are not implemented.** Listing profiles, reading any profile, and reactivating a profile are designed but not built (`GET /api/users`, `GET /api/users/{auth_user_id}`, `POST /api/users/{auth_user_id}/reactivate`). The `require_admin` dependency exists and is tested, but no route uses it.
- **A deactivated profile cannot be reactivated through the API**, because reactivation is one of the missing admin endpoints. Its records are kept in the database.
- **Each protected request calls the Authentication Service.** Results are not cached. If that service is down, protected endpoints return 503.
- **No limit on addresses per customer, and no rate limiting.** These are security audit findings 2 and 3, still open.
- **Swagger UI is on by default** (`DOCS_ENABLED=true`). Turn it off in production.
- **Not tested live:** a real token reaching its 30-minute expiry, and an account deactivated in the Authentication Service. Both are covered only by automated tests with the Authentication Service stand-in.
- The Swagger UI walkthrough in `DELIVERABELS/screenshots/` was driven by a script (`scripts/capture_swagger_screenshots.py`, Edge via Playwright), not clicked by hand. The Postman collection was run with Newman, not in the Postman app.
- **Not added to the platform-level Docker Compose or API gateway.** The service runs as its own Compose project.
- **One pytest warning:** a Starlette deprecation warning from FastAPI's `TestClient`. It is in a third-party library and affects the tests only.
