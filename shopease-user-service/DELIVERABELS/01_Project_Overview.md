# 01 – Project Overview: ShopEase User Service

| | |
| --- | --- |
| Service | `shopease-user-service` |
| Type | Independent FastAPI microservice |
| Duration | Two-day task |
| Started | 10 November 2026 |
| Completed | 11 November 2026: everything except admin endpoints (see [09](09_Final_Completion_Report.md)) |
| Depends on | ShopEase Authentication Service (JWT only) |

## Objective

Build an independent microservice that manages customer profiles and saved delivery addresses:
- **Identity:** taken from tokens issued and verified by the existing Authentication Service. The service never holds that service's JWT secret.
- **Ownership:** no customer can read or change another customer's data.
- **Database:** its own MySQL database, migrated with Alembic.
- **Delivery:** runs in Docker Compose, with automated tests and documentation.

## Purpose

The User Service stores the information about a customer that is not part of logging in:

- **User profile:** full name, phone number, date of birth, and profile image URL.
- **Saved addresses:** any number of shipping or billing addresses per user, with exactly one default address once at least one exists.

Other ShopEase services, such as Order and Checkout, can use it later to read a customer's default delivery address.

## What it does not do

- It does not register users, log users in, or store passwords. That is the Authentication Service's job.
- It does not create or decode JWTs, and it holds no JWT secret. The Authentication Service checks every token.
- It does not read the Authentication Service's database.

## Relationship with the Authentication Service

```
 Client                    Authentication Service (8001)            User Service (8002)
   |  POST /api/auth/login        |                                        |
   |----------------------------->|  checks password, signs JWT            |
   |<-----------------------------|  { access_token }                      |
   |                                                                       |
   |  GET /api/users/profile  Authorization: Bearer <access_token>             |
   |---------------------------------------------------------------------->|
   |                              |  POST /api/auth/verify-token           |
   |                              |<---------------------------------------|
   |                              |  same Authorization header, no body    |
   |                              |--------------------------------------->|
   |                              |  200 {valid, user{id, role, ...}}      |
   |                              |  or 401 / 403                          |
   |<----------------------------------------------------------------------|
   |  profile of user <user.id>                                            |
```

- **Verify endpoint:** `POST /api/auth/verify-token` on the Authentication Service. This was checked against its code (`app/routers/auth_routes.py` and `app/schemas/auth_schema.py`). It takes only the `Authorization: Bearer` header and returns:
  - `200 {"valid": true, "user": {"id", "full_name", "email", "role", "is_active"}}`
  - `401 {"detail": "Could not validate credentials"}` for a missing, invalid or expired token, or a user that no longer exists
  - `403 {"detail": "Inactive user"}`
- **How the User Service answers:** 200 continues with that user. A 401 or 403 is passed on to the caller unchanged. A timeout, connection failure, 5xx, or unexpected body gives `503 Authentication service unavailable`.
- **Linking data:** `user_profiles.auth_user_id` stores `user.id`. It is unique, so each auth user has at most one profile. It is not a database foreign key, because each service owns its own database.
- **Immediate deactivation:** the Authentication Service checks its database on each verify call, so a deleted or deactivated user is rejected at once, not only when the token expires.
- **Authorization:** a user can only reach their own profile and addresses, because the owner always comes from the verified user and never from the request body or URL. A `require_admin` dependency (`role == "ADMIN"`) exists and is tested. The admin endpoints that would use it are planned but **not implemented**.
- **Dependency at run time:** if the Authentication Service is down, protected endpoints return 503. The `/health` and `/health/db` endpoints still work.

## Configuration

All settings come from environment variables or `.env`, through Pydantic Settings (`app/core/config.py`). `.env` is excluded by `.gitignore` and `.dockerignore`. `.env.example` holds only placeholders.

| Group | Variables |
| --- | --- |
| Database | `MYSQL_DATABASE=shopease_user_db`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_HOST`, `MYSQL_PORT` |
| Authentication Service | `AUTH_SERVICE_VERIFY_URL` (default `http://127.0.0.1:8001/api/auth/verify-token`), `AUTH_SERVICE_TIMEOUT_SECONDS` (default 5) |
| Docker only | `MYSQL_ROOT_PASSWORD`, `DOCKER_AUTH_SERVICE_VERIFY_URL` (`http://host.docker.internal:8001/...`), `USER_SERVICE_HOST_PORT` |

The only secrets are the two MySQL passwords. They have no defaults, are masked in logs and the connection URL, and a `change-me` placeholder stops startup.

## Technology

| Area | Choice |
| --- | --- |
| Language | Python 3.11+ |
| Framework | FastAPI 0.162, Uvicorn 0.54 |
| Database | MySQL 8.4, SQLAlchemy 2.1, PyMySQL 1.2, Alembic 1.20 |
| Validation and settings | Pydantic 2.14, pydantic-settings 2.16 |
| Calls to the Authentication Service | HTTPX 0.28 |
| Containers | Docker, Docker Compose |
| Tests | pytest 9.2, FastAPI TestClient |

The service has no JWT or password-hashing libraries.

## Ports

| Component | Port |
| --- | --- |
| Authentication Service API | 8001 |
| User Service API | 8002 |
| Product Service API | 8003 |
| Auth MySQL (host) | 3308 |
| User MySQL (host) | 3309, only with `docker-compose.dev.yml`. In the normal Compose setup it is not published |

## API summary

15 endpoints, all implemented and tested. The full contract is in [04](04_API_Documentation.md).

| Area | Endpoints |
| --- | --- |
| Profile | `POST`, `GET`, `PUT`, `PATCH`, `DELETE` `/api/users/profile` |
| Account | `GET /api/users/account`, `PATCH /api/users/account/contact`, `PATCH /api/users/account/deactivate` |
| Addresses | `POST`, `GET` `/api/users/addresses`; `GET /api/users/addresses/default`; `GET`, `PUT`, `DELETE` `/api/users/addresses/{address_id}`; `PATCH /api/users/addresses/{address_id}/default` |
| Service | `GET /`, `/health`, `/health/db` (no token) |

## Deliverables in this folder

| File | Contents |
| --- | --- |
| [Development_Checklist.md](Development_Checklist.md) | Two-day task checklist |
| 02 / 03 | Day 1 and Day 2 progress |
| 04 | API documentation |
| 05 | Database schema |
| 06 | JWT integration report |
| 07 | API testing report |
| 08 | Docker execution report |
| 09 | Final completion report |
| 10 | Teams progress updates |
| `Word_Documents/` | Four Word documents for submission, generated from these reports |
| `Test_Results/` | Raw pytest, live API, Newman and Docker output (sanitized) |
| `screenshots/` | 25 evidence screenshots from the running system, indexed in its README |
