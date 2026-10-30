# ShopEase

A microservices e-commerce backend: five FastAPI services (authentication, users, products
and inventory, orders, payments), each owning its own MySQL database, behind a single API
Gateway, packaged with Docker Compose. Payments run against a **mock provider only**: no
real money can move.

> **Status (2026-10-30):** all six components implemented and verified. Results of the final
> run: 374 unit/API tests, 65 MySQL integration tests, 54 cross-service tests and a 38-request
> Postman collection, all passing — see [docs/testing_report.md](docs/testing_report.md).
> Limitations are listed [below](#limitations). Not independently security-reviewed.

## Architecture

```
Client ──► API Gateway :8000 ──► auth :8001 ── auth_db
           (routing, edge JWT,  ├► user :8002 ── user_db
            rate limits,        ├► product :8003 ── product_db
            request IDs)        ├► order :8004 ── order_db      order → product, order → user
                                └► payment :8005 ── payment_db  payment → order, payment → mock provider
                                     (all five databases: one MySQL 8.4 server, separate users)
```

- **Database per service:** each service connects only to its own database with its own
  least-privilege users; data crosses service boundaries only through REST APIs.
- **Security:** RS256 access tokens verified at the gateway **and** in every service;
  authorization (roles, scopes, ownership) in the owning service; internal calls need scoped
  service tokens; `/internal/*` is never routed by the gateway.
- **Checkout:** two steps (create order → pay). Stock is reserved with row locks, payments
  are idempotent, unknown payment outcomes are reconciled rather than re-charged.

Diagram and details: [docs/final_architecture.md](docs/final_architecture.md).

| Component | Port | Database | Swagger UI |
|-----------|------|----------|------------|
| API Gateway (client entry point) | 8000 | — | http://127.0.0.1:8000/docs |
| Authentication Service | 8001 | `auth_db` | http://127.0.0.1:8001/docs |
| User Service | 8002 | `user_db` | http://127.0.0.1:8002/docs |
| Product Service | 8003 | `product_db` | http://127.0.0.1:8003/docs |
| Order Service | 8004 | `order_db` | http://127.0.0.1:8004/docs |
| Payment Service | 8005 | `payment_db` | http://127.0.0.1:8005/docs |
| MySQL 8.4 | not published | all five | `docker compose exec mysql mysql -uroot -p` |

## Prerequisites

- Docker with Compose v2 (verified: Docker Desktop, Engine 29.6.2, Compose v5.3.1).
- Python 3.12+ for the helper scripts and for running tests outside Docker (verified on 3.12
  and 3.14).
- Optional: Postman or Newman for the API collection.

## Quick start (Docker)

```bash
python scripts/generate_jwt_key.py     # once: secrets/jwt_private.pem (git-ignored)
python scripts/init_dev_env.py         # once: .env with random development passwords (git-ignored)
docker compose up --build -d --wait    # MySQL → migrations → service clients → services → gateway
curl http://127.0.0.1:8000/health/ready
```

Create the first admin after registering that account:
`docker compose exec auth_service python -m app.cli promote-admin admin@example.com`.

A port already in use? Set e.g. `PAYMENT_SERVICE_HOST_PORT=8015` in `.env`.

## Environment configuration

All configuration comes from environment variables; `.env.example` documents every one of
them with placeholders only. `scripts/init_dev_env.py` copies it to `.env` and generates a
random value for each `change-me`. Never commit `.env` or `secrets/`.

| Group | Variables |
|-------|-----------|
| Common | `APP_ENV`, `LOG_LEVEL`, `DOCS_ENABLED` |
| MySQL | `MYSQL_ROOT_PASSWORD`; per service `<SVC>_DB_NAME`, `_DB_USER`, `_DB_PASSWORD`, `_DB_MIGRATION_USER`, `_DB_MIGRATION_PASSWORD` |
| Tokens | `JWT_PRIVATE_KEY_PATH` (auth only), `JWT_ISSUER`, `JWT_AUDIENCE`, `JWT_ACCESS_TOKEN_MINUTES`, `REFRESH_TOKEN_DAYS`, `JWKS_URL` |
| Service clients | `ORDER_SERVICE_CLIENT_SECRET`, `PAYMENT_SERVICE_CLIENT_SECRET` |
| Gateway | `*_SERVICE_URL`, `UPSTREAM_*_TIMEOUT_SECONDS`, `RATE_LIMIT_*_PER_MINUTE`, `MAX_REQUEST_BODY_BYTES`, `CORS_ALLOWED_ORIGINS` |
| Jobs | `RESERVATION_*`, `ORDER_SWEEP_SECONDS`, `STUCK_PENDING_SECONDS`, `PAYMENT_SWEEP_SECONDS` |
| Payments | `PAYMENT_PROVIDER=mock` (development only; refused when `APP_ENV=production`) |
| Host ports | `GATEWAY_HOST_PORT`, `<SVC>_SERVICE_HOST_PORT` (bound to 127.0.0.1) |

## Database and migrations

One MySQL server hosts five databases. On first start (empty volume) the init script creates
the databases and, per service, a runtime user (DML) and a migration user (DDL), each limited
to its own database. Each service has its own Alembic history.

```bash
docker compose up -d --wait                                # runs every *_migrate job before its service
docker compose run --rm order_migrate                      # migrate one service again
docker compose run --rm order_migrate alembic current      # its current revision
docker compose down                                        # stop, keep data
docker compose down -v                                     # stop and DELETE all data
```

| Database | Migrations (head last) |
|----------|------------------------|
| `auth_db` | `auth_0001` |
| `user_db` | `user_0001` |
| `product_db` | `product_0001`, `product_0002` |
| `order_db` | `order_0001`, `order_0002` |
| `payment_db` | `payment_0001`, `payment_0002` |

Tables, columns and constraints as implemented: [docs/database_ownership.md](docs/database_ownership.md).
MySQL without Docker: [docs/database_setup.md](docs/database_setup.md).

## Docker commands

```bash
docker compose up --build -d --wait     # build and start everything
docker compose ps                       # status and health
docker compose logs -f order_service    # JSON logs of one service
docker compose restart order_service    # restart one service on its own
docker compose exec auth_service python -m app.cli --help
docker compose down                     # stop (data kept in the mysql_data volume)
```

Startup order, isolation (MySQL not published, gateway can't reach the database), health
checks and restart behaviour: [docs/local_development.md](docs/local_development.md).

## API documentation

- Swagger UI per component at `http://127.0.0.1:<port>/docs` (table above); OpenAPI JSON at
  `/openapi.json`. Exported copies: [docs/openapi/](docs/openapi/) (regenerate with
  `python scripts/export_openapi.py`).
- Every endpoint, its access level and success codes: [docs/api_reference.md](docs/api_reference.md).
- Contracts, status codes and error format: [docs/rest_api_notes.md](docs/rest_api_notes.md).
- Postman: [postman/](postman/) (collection + environment template with placeholders).

Clients call the gateway with `/api/...` paths. Every error is
`{"error": {"code", "message", "details"?, "request_id"}}`.

## Running without Docker

```bash
py -3.14 -m venv .venv && .venv/Scripts/activate     # macOS/Linux: python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python scripts/init_local_databases.py --dry-run      # then without --dry-run, against your own MySQL
alembic -c services/auth_service/alembic.ini upgrade head   # repeat per service
uvicorn app.main:app --app-dir services/auth_service --port 8001   # one terminal per component
```

## Testing

```bash
python scripts/run_tests.py                 # unit + API tests, every component (no network, no MySQL)
python scripts/run_tests.py -m unit --cov   # one layer, with coverage
python scripts/run_integration.py           # cross-service tests on a disposable Docker stack
```

Database integration tests need a disposable MySQL (`SHOPEASE_MYSQL_TESTS=1`). Layers and
coverage map: [docs/testing.md](docs/testing.md); latest results: [docs/testing_report.md](docs/testing_report.md).

## Project layout

| Path | Contents |
|------|----------|
| `api_gateway/` | Gateway: `app/` (routing, edge checks, proxy), tests, Dockerfile |
| `services/<name>_service/` | `app/` (main, config, db, models, schemas, api routers, business logic), `migrations/`, `alembic.ini`, tests, Dockerfile, requirements |
| `shared/` | `shopease-shared`: logging, request IDs, error envelope, health routes, token verification, OpenAPI helpers (no business logic) |
| `tests/integration/` | Cross-service tests (disposable Docker stack) |
| `postman/` | Postman collection and environment template |
| `deploy/mysql/init/` | Database and user creation on first start |
| `scripts/` | Dev env, keys, admin CLI, local DB init, test runners, OpenAPI/schema export |
| `docs/` | Day 1 design, Day 2 implementation docs, reports ([index](docs/README.md)) |

## Limitations

- **Payments:** mock provider only; no provider webhooks (`501`); no real money can move.
- **Auth:** access tokens can't be revoked before they expire (15 min); rate limits are
  in-memory per gateway process; no MFA, email verification or password reset.
- **Data:** one MySQL server in development; no backups, replicas or TLS in the local stack.
- **Workflows:** refunded paid orders don't return stock automatically; no admin tool for
  payments flagged for manual review; no returns process.
- **Operations:** background jobs run in every service instance (idempotent, uncoordinated);
  no CI/CD, no load testing, no frontend; Docker verified on Windows only.

Full list with context: [docs/final_architecture.md §8](docs/final_architecture.md#8-known-limitations)
and [docs/day2_progress.md](docs/day2_progress.md).
