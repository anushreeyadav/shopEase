# 08 – Docker Execution Report

| | |
| --- | --- |
| Date | 11 November 2026 |
| Host | Windows 11 Pro, Docker Desktop: Docker Engine 29.6.2, Docker Compose v5.3.1 |
| Images | `shopease-user-service:dev` (built from `Dockerfile`, 339 MB, Python 3.11.18), `mysql:8.4` (MySQL 8.4.11) |
| Result | **Both containers healthy. The User Service connects to MySQL through `user-mysql`, and tokens from the running Authentication Service are verified successfully.** |

All results below come from commands actually run on that date. Saved output is in [`Test_Results/`](Test_Results/), with every password from `.env` replaced by `<redacted>` and no access token included.

## Configuration

### Dockerfile

| Requirement | Implementation |
| --- | --- |
| Python 3.11 | `FROM python:3.11-slim-bookworm` |
| Working directory | `WORKDIR /app` |
| Copy `requirements.txt`, install dependencies | Copied first and installed with `pip install -r requirements.txt`, so the dependency layer is reused until the file changes |
| Copy application source | Only `app/`, `alembic/` and `alembic.ini`. `.dockerignore` also excludes `.env*`, `.venv`, tests, deliverables and Git data |
| Expose 8002 | `EXPOSE 8002` |
| Uvicorn startup | `CMD sh -c "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8002"` |
| Runs as | Unprivileged user `app` (uid 999) |
| Health check | `GET http://127.0.0.1:8002/health` every 10 s, start period 30 s |

### docker-compose.yml

| Service | Configuration |
| --- | --- |
| `user-mysql` | `mysql:8.4`. `MYSQL_DATABASE` (default `shopease_user_db`), `MYSQL_USER`, `MYSQL_PASSWORD` and `MYSQL_ROOT_PASSWORD` from `.env`. The passwords have no defaults, and Compose refuses to start without them (`${VAR:?set in .env}`). Named volume `user_mysql_data:/var/lib/mysql`. Health check: `mysqladmin ping` over TCP every 5 s, start period 30 s. **No published port** |
| `user-service` | `build: .`. All settings come from environment variables, which Compose fills from `.env`. `MYSQL_HOST: user-mysql`, `MYSQL_PORT: 3306` (never localhost). `AUTH_SERVICE_VERIFY_URL` from `DOCKER_AUTH_SERVICE_VERIFY_URL`, default `http://host.docker.internal:8001/api/auth/verify-token`. `extra_hosts: host.docker.internal:host-gateway`. Published on `127.0.0.1:8002` only. `depends_on: user-mysql: condition: service_healthy, restart: true` |

### Startup and readiness

1. Compose starts `user-mysql` and waits until its health check passes. The TCP ping fails during MySQL's first-run initialisation, so "healthy" means the real server is accepting connections.
2. Only then does it start `user-service`. Its command runs `alembic upgrade head`. `alembic/env.py` refuses any database other than `shopease_user_db`.
3. **Uvicorn starts only if the migration succeeded** (`&&`), so the port is not open, and no request is accepted, before the schema is current. A failed migration stops the container, and `restart: unless-stopped` retries.
4. `exec` makes Uvicorn PID 1, so it receives `docker stop` signals and shuts down cleanly.
5. The container becomes `healthy` once `/health` answers. `docker compose up --wait` waits for this.
6. If `user-mysql` restarts, `restart: true` restarts `user-service` too.

### Authentication Service connectivity

| | |
| --- | --- |
| Authentication Service | Its own Compose project, `shopease-auth-service`, with its own network. It publishes its API on `127.0.0.1:8001` of the host |
| Why not `http://auth-service:8001` | Service names resolve only inside one Compose project's network. `auth-service` does not exist on `shopease-user-service_default` |
| URL used | `http://host.docker.internal:8001/api/auth/verify-token`. Docker Desktop resolves `host.docker.internal` to the host, and `host-gateway` does the same on Linux |
| Verified | From inside the `user-service` container, `POST` to that URL without a token returned `401 {"detail":"Could not validate credentials"}`: the endpoint is reachable |
| Override | Set `DOCKER_AUTH_SERVICE_VERIFY_URL` in `.env`, for example if the Authentication Service is published on another port or host |

### Security

| Requirement | Evidence |
| --- | --- |
| `.env` not copied into the image | `.dockerignore` excludes `.env` and `.env.*`, and the Dockerfile copies only named folders. **Checked in the built image:** `find / -name '.env*'` found nothing. `/app` contains only `alembic`, `alembic.ini`, `app`, `requirements.txt` |
| No hard-coded secrets | Image environment (`docker image inspect`): only `PATH`, `LANG`, `PYTHON_*`, `PIP_*`, `APP_ENV=production`, `LOG_LEVEL=INFO`, and `GPG_KEY` (the public fingerprint of Python's release-signing key, set by the official base image). Passwords are supplied by Compose at run time from `.env` |
| `.env` excluded from Git | `git check-ignore -v .env`: `.gitignore:6:.env`. `git ls-files .env`: not tracked |
| MySQL not exposed unnecessarily | No `ports` on `user-mysql`. `docker port` shows nothing, and `127.0.0.1:3309` is unreachable from the host. Only `user-service` reaches it, over the project network. For development on the host, `docker-compose.dev.yml` publishes it on `127.0.0.1:3309` (loopback only) when added explicitly |
| API not exposed to the network | Published on `127.0.0.1:8002`, not `0.0.0.0` |
| Unprivileged container | `id` in the container: `uid=999(app) gid=999(app)` |

Container environment variables, including the database password, are visible to anyone with access to the Docker engine (`docker inspect`). That is normal for Compose environment configuration. Docker secrets would be the next step for a production deployment.

## Commands and results

| # | Command | Result | Output |
| --- | --- | --- | --- |
| 1 | `docker compose config` | Exit 0. Resolved: `API_PREFIX: /api`, `MYSQL_HOST: user-mysql`, `AUTH_SERVICE_VERIFY_URL: http://host.docker.internal:8001/api/auth/verify-token`. Only one published port: 8002 | [`docker_compose_config.txt`](Test_Results/docker_compose_config.txt) (3 passwords redacted) |
| 2 | `docker compose up --build -d` | Image built. `user-mysql` started and became healthy before `user-service` started | [`docker_compose_up.txt`](Test_Results/docker_compose_up.txt) |
| 3 | `docker compose ps` | `user-mysql` Up (healthy), ports `3306/tcp, 33060/tcp` (not published). `user-service` Up (healthy), `127.0.0.1:8002->8002/tcp` | [`docker_compose_ps.txt`](Test_Results/docker_compose_ps.txt) |
| 4 | `docker compose logs -f user-service` (followed for 15 s) | Alembic ran, then `Uvicorn running on http://0.0.0.0:8002`, then `GET /health 200` | [`docker_compose_logs_user_service.txt`](Test_Results/docker_compose_logs_user_service.txt) |

### User Service ↔ MySQL

| Check | Result |
| --- | --- |
| `GET http://127.0.0.1:8002/health` | `200 {"status":"ok","service":"ShopEase User Service","version":"0.1.0"}` |
| `GET http://127.0.0.1:8002/health/db` | `200 {"status":"ok","database":"connected"}` |
| Connection from inside the container | Connected to `shopease_user_db` @ `user-mysql`, Alembic version `4f1a9d27c5e3`, tables `alembic_version`, `user_addresses`, `user_profiles` |
| Migrations on a **new, empty database** | Separate project `shopease-user-migration-check` with its own volume (port 18002): `Running upgrade -> 8c2e3b6d4acf`, then `Running upgrade 8c2e3b6d4acf -> 4f1a9d27c5e3`, **then** `Started server process`. Healthy after 27 s, and `/health/db` 200. The project and its volume were then removed with `down -v`. [`docker_fresh_database_migration_log.txt`](Test_Results/docker_fresh_database_migration_log.txt) |
| Persistence | Before `docker compose down`: 1 profile and 1 address for auth user 1. After `docker compose up -d --wait`: the same 1 and 1 |

Details: [`docker_verification_checks.txt`](Test_Results/docker_verification_checks.txt).

### Authentication Service token verification

The Authentication Service was started from its own folder, unchanged, with `docker compose up -d --build --wait`. Both its containers became healthy, with the API on `127.0.0.1:8001`. A test user was registered, and every call below used the real access token from its login.

| # | Request | Result |
| --- | --- | --- |
| 1 | `POST :8001/api/auth/register` (test user `docker.check.1794374005@example.com`) | 201, user id 1 |
| 2 | `POST :8001/api/auth/login` | 200, access token `eyJhbGciOi…` (redacted) |
| 3 | `POST :8001/api/auth/verify-token` directly | 200 `{"valid":true,"user":{"id":1,…}}` |
| 4 | `GET :8002/api/users/account` with the token | **200**, `authentication_account.auth_user_id = 1`: the user-service container verified the token through `host.docker.internal:8001` and used the returned identity |
| 5 | `POST :8002/api/users/profile` | 201, `auth_user_id: 1` |
| 6 | `POST :8002/api/users/addresses` | 201, `is_default: true` |
| 7 | `GET :8002/api/users/addresses/default` | 200, the same address |
| 8 | Same token with its signature altered | 401 `Could not validate credentials` (rejected by the Authentication Service) |
| 9 | No token | 401 |
| 10 | Authentication Service container stopped, valid token | **503** `Authentication service unavailable`. It fails closed; the token is not trusted |
| 11 | Authentication Service started again, same token | 200 |
| 12 | Token in logs | Not found in the `user-service` log or the `auth-service` log (searched for the whole token and its signature) |

The `user-service` log shows each request followed by `POST http://host.docker.internal:8001/api/auth/verify-token "HTTP/1.1 200 OK"`, and `Authentication service request failed: ConnectError` during step 10. Full sanitized output: [`docker_auth_token_verification.txt`](Test_Results/docker_auth_token_verification.txt).

### Test suite after the Docker changes

| Command | Result | Output |
| --- | --- | --- |
| `pytest -v` (SQLite) | **518 passed** | [`pytest_after_docker_sqlite.txt`](Test_Results/pytest_after_docker_sqlite.txt) |
| `USER_SERVICE_TEST_DB=mysql pytest -v` (MySQL published through `docker-compose.dev.yml`) | **518 passed**. Afterwards only the Docker check's 1 profile and 1 address were in the database | [`pytest_after_docker_mysql.txt`](Test_Results/pytest_after_docker_mysql.txt) |

## Issues

| # | Issue | Resolution |
| --- | --- | --- |
| 1 | The first `docker compose up` left `user-service` restarting: `AssertionError: A path prefix must start with '/'`. The cause was the shell used for the test, not the configuration. `.env` had been loaded into a Git Bash session, Git Bash rewrote `API_PREFIX=/api` to `C:/Program Files/Git/api` when starting `docker.exe`, and Compose gives an exported variable priority over `.env`. In a clean environment and in PowerShell, `docker compose config` shows `/api` | All Docker commands were rerun from PowerShell (results above). `API_PREFIX` is now validated in `app/core/config.py`, so a wrong value stops the service with a clear settings error. 8 new tests. The README warns against running Compose from Git Bash with exported `.env` variables |
| 2 | MySQL was published on `127.0.0.1:3309` in the main Compose file, although the service container does not need it | Removed from `docker-compose.yml`. `docker-compose.dev.yml` publishes it on demand for Alembic and pytest on the host |
| 3 | With real data in the database, 33 MySQL-mode tests failed. Three address tests checked that the **whole table** was empty, not just the test user's addresses | Those assertions now check only the test profile's addresses. 518 passed with data present |

## Final validation (later on 11 November 2026)

After the documentation work, these were run against the same containers:
- `docker compose config --quiet` exited 0, with and without `docker-compose.dev.yml`. Resolved values: `API_PREFIX: /api`, `MYSQL_HOST: user-mysql`, the `host.docker.internal` verify URL, and 8002 as the only published port.
- Both containers were healthy. `alembic current` inside the container showed `4f1a9d27c5e3 (head)`, and `alembic check` reported "No new upgrade operations detected".
- The live audit of every endpoint passed 73/73, and the Postman collection with Newman passed 38/38 assertions ([07](07_API_Testing_Report.md#live-api-tests-docker-real-authentication-service)).
- `pytest` passed 518 on SQLite and 518 on MySQL. For the MySQL run, MySQL was published briefly through `docker-compose.dev.yml`, then `docker compose up -d` restored the unpublished setup.

Output: [`final_validation_checks.txt`](Test_Results/final_validation_checks.txt).

## Current state

- **`shopease-user-service`:**
  - Both containers are running and healthy, with MySQL not published.
  - The volume `shopease-user-service_user_mysql_data` holds test data only: 8 profiles (4 of them deactivated by the tests) and 11 addresses.
  - These belong to Authentication Service users 1–8, created by the token check, the Newman run and the live audits.
- **`shopease-auth-service`:**
  - Built and started for these tests. Its source files were not changed.
  - Its volume `shopease-auth-service_auth_mysql_data` holds 8 test users, all `@example.com`:
    - `docker.check.*`: the token check
    - `final.audit.*`: the live audits
    - `postman.*`: the Newman run

To stop everything: `docker compose down` in each folder. Add `-v` to delete that service's data.
