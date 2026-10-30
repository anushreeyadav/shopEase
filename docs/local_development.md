# Local Development with Docker Compose

Runs the whole system (MySQL, five services, the gateway) on one machine. **Development
only**: the payment provider is a mock, secrets are generated locally, TLS is not configured.

Verified on 2026-10-30 with Docker Desktop (Engine 29.6.2, Compose v5.3.1) on Windows 11:
all images built, the stack started healthy from an empty volume, and the checks in §6
passed.

---

## 1. First start

```bash
python scripts/generate_jwt_key.py     # secrets/jwt_private.pem   (git-ignored)
python scripts/init_dev_env.py         # .env with random passwords (git-ignored, refuses to overwrite)
docker compose up --build -d --wait    # returns when everything is healthy (~30s after the build)
```

Then: gateway `http://127.0.0.1:8000`, Swagger UI per service at
`http://127.0.0.1:<port>/docs` (8001–8005). Create the first admin after registering the
account: `docker compose exec auth_service python -m app.cli promote-admin you@example.com`.

**Port already in use?** Set e.g. `PAYMENT_SERVICE_HOST_PORT=8015` in `.env` (the template
lists all `*_HOST_PORT` variables). Every published port binds to `127.0.0.1` only.

## 2. What starts, in which order

```
mysql (healthy)
 ├─► auth_migrate ─► auth_bootstrap ─► auth_service ─┐
 ├─► user_migrate ─────────────────► user_service ──┤
 ├─► product_migrate ──────────────► product_service ┼─► api_gateway
 ├─► order_migrate ──(+ bootstrap)─► order_service ──┤
 └─► payment_migrate ─(+ bootstrap)► payment_service ┘
```

| Container | Kind | Ready when |
|-----------|------|------------|
| `mysql` (`mysql:8.4`) | database | `mysqladmin ping` over TCP succeeds (not during first-run initialisation) |
| `<svc>_migrate` (×5) | one-off job | exits 0 after `alembic upgrade head` with that service's **migration** user |
| `auth_bootstrap` | one-off job | exits 0 after registering `svc:order` and `svc:payment` with the client secrets from `.env` (idempotent) |
| five services | `restart: unless-stopped` | `GET /health/ready` returns 200 (their own database is reachable) |
| `api_gateway` | `restart: unless-stopped` | `GET /health`; starts after all five services are healthy |

Images: `python:3.12-slim-bookworm`, dependencies installed from each service's own pinned
`requirements.txt`, code owned by root, processes run as the unprivileged user `10001`
(no login shell). Every image has a liveness `HEALTHCHECK`; Compose replaces it with the
readiness check for the business services.

## 3. Isolation and secrets

- Networks: `data` (MySQL, services, jobs) and `edge` (services, gateway). The **gateway
  can't reach MySQL**; **MySQL is not published** to the host.
- Containers address each other by service name (`http://order_service:8004`, `mysql`).
- Each container receives only its own variables: a service gets its runtime DB password
  (and, for order/payment, its client secret); migration jobs get only migration passwords;
  the gateway gets no database or client secrets. MySQL gets the database passwords its init
  script needs.
- The JWT private key is a Compose **secret** mounted read-only into `auth_service` only.
- No secret is in a Dockerfile, in source code or in committed configuration. `.env` and
  `secrets/` are git-ignored, and `.dockerignore` keeps them, keys, tests and docs out of
  every build context.

## 4. Databases and migrations

**Initialisation** happens once, when the `mysql_data` volume is empty:
`deploy/mysql/init/01-create-databases.sh` creates `auth_db`, `user_db`, `product_db`,
`order_db`, `payment_db`, and per service a runtime user (DML on its database) and a
migration user (DDL on its database). It never runs again on an existing volume.

```bash
docker compose up -d --wait                                   # runs all *_migrate jobs, then starts services
docker compose run --rm order_migrate                         # migrate one service again
docker compose run --rm order_migrate alembic current         # show its revision
docker compose run --rm order_migrate alembic history         # list its migrations
docker compose exec mysql mysql -uroot -p                     # SQL shell (root password from .env)
docker compose down                                           # stop; keeps the data volume
docker compose down -v                                        # stop and DELETE all database data
```

More on migrations (writing new ones, review rules): [database_setup.md](database_setup.md).

## 5. Mock payments (development only)

`payment_service` runs with `PAYMENT_PROVIDER=mock`, fixed in `docker-compose.yml`. The mock
moves **no money** and contacts nothing outside the container; payment_service **refuses to
start** with it when `APP_ENV=production`. Pay with tokens such as `mock_tok_success` or
`mock_tok_decline` (full list: [payment_processing.md](payment_processing.md) §4).

## 6. Verification results (2026-10-30)

| Check | Result |
|-------|--------|
| `docker compose config` | valid; secrets scoped per container; ports on 127.0.0.1; MySQL unpublished |
| `docker compose build` | 6 images built (270–316 MB) |
| First start from an empty volume | init script created 5 databases and 10 users; 5 migrations and the bootstrap exited 0; all 7 long-running containers healthy |
| Health and database connectivity | every service `/health/ready` → `{"database": "ok"}`; gateway ready over service DNS names |
| Isolation | containers run as uid 10001; the gateway can't open a connection to `mysql:3306`; MySQL has no host port binding |
| Checkout through the gateway | register, login, admin product, `409` out of stock, order `AWAITING_PAYMENT`, mock payment `SUCCEEDED`, order `PAID`, stock deducted once |
| Live smoke tests (`tests/`) | 19 passed against the containers |
| Restarts | see §7 |
| Logs | no passwords, tokens or card data; no ERROR lines after the fix below |

Found during verification and fixed: order_service and payment_service crashed on start with
`ModuleNotFoundError: httpx`. Their `requirements.txt` lacked `httpx` (the shared local
virtual environment had it from the gateway's requirements, so local tests passed). An
import-vs-requirements audit of all components found no other gaps.

## 7. Restarts and recovery

| Action | Measured | Recovery behaviour |
|--------|----------|--------------------|
| `docker compose restart order_service` | healthy again in ~7s | Other containers unaffected; checkout works afterwards (service token re-fetched) |
| `docker compose restart auth_service` | ~7.5s | Existing access tokens keep working: the signing key comes from the secret, so it is the same key |
| `docker compose restart api_gateway` | ~7s | Stateless apart from rate-limit counters (reset) and the JWKS cache (re-fetched) |
| `docker compose restart mysql` | ~10s | Data persists in the volume. Services reconnect on their own (`pool_pre_ping`); checkout works again afterwards |
| `docker compose stop product_service` | — | Browsing answers `503`; order creation answers `503/504` and stores nothing; `start` brings it back |

**Recovery limitations**

- While MySQL restarts (~10s), requests to the services answer `503 DATABASE_UNAVAILABLE`,
  and background jobs log one WARNING per run and retry on the next one.
- `depends_on` only orders the **first** start. Docker restarts a container that **exits**,
  but not one that is merely unhealthy. A service whose database stays down keeps running
  and answers `503` until it comes back.
- In-memory state is lost on restart: gateway rate-limit counters; the **mock** provider's
  records (an unresolved `PROCESSING` payment then reconciles to `FAILED`
  `not_found_at_provider`); cached JWKS keys and service tokens (re-fetched, harmless).
- Without `secrets/jwt_private.pem`, Compose refuses to start (the secret file is required).
  A temporary key is only used outside Compose (`APP_ENV=development`, no key configured),
  and would invalidate all tokens on every auth restart.
- Passwords in `.env` are applied **only when the volume is first created**. Changing them
  later needs `ALTER USER` in MySQL, or `docker compose down -v` (deletes all data).
- Migrations run on `docker compose up`. After pulling new migrations into a running stack,
  run `docker compose up -d --wait` (or the specific `*_migrate` job) before using the new code.
- Each `up` re-runs `auth_bootstrap`; it is idempotent and keeps an unchanged secret's hash.
