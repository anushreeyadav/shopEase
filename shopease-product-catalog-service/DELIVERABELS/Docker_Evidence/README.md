# Docker: execution instructions and evidence

Task 10, recorded on 12 November 2026 (times in the files are UTC) with Docker 29.6.2 and Docker
Compose v5.3.1 on Docker Desktop (Windows, Linux engine). Every file in this folder is unedited
command output; the commands are at the top of each file or on the `$` lines.

## 1. What runs

| Compose service | Image | Role | Reached at |
|---|---|---|---|
| `catalog-service` | `shopease-product-catalog-service:dev`, built from `Dockerfile` (`python:3.11-slim-bookworm`) | FastAPI API | `http://127.0.0.1:8006` on this machine only |
| `catalog-mysql` | `mysql:8.4` | Database `shopease_product_catalog_db` | `catalog-mysql:3306` inside the Compose network only |

| Requirement | Where |
|---|---|
| Python 3.11 base image | `Dockerfile`: `FROM python:3.11-slim-bookworm`; inside the container `Python 3.11.18` (05) |
| Dependencies from `requirements.txt` | `Dockerfile`: `COPY requirements.txt .` then `RUN pip install -r requirements.txt` |
| Database `shopease_product_catalog_db` | Fixed in `docker-compose.yml` for both services, not taken from the shell or `.env` (05: `MYSQL_DATABASE=shopease_product_catalog_db`) |
| Credentials from the environment | `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD` come from `.env` and are required (`${VAR:?set in .env}`); Compose stops if one is missing |
| Named volume | `catalog_mysql_data` mounted at `/var/lib/mysql` (06); kept by `docker compose down` (09) |
| MySQL health check | The service's own user runs `SELECT 1` in `shopease_product_catalog_db` over TCP; the password is passed through the environment, not the command line (06: `status=healthy`) |
| Wait for MySQL | Compose starts the API only when MySQL is healthy (`depends_on: condition: service_healthy`, 02). The image also waits by itself: `python -m app.database.wait --timeout 60` (08) |
| Database by service name | `MYSQL_HOST=catalog-mysql`, `MYSQL_PORT=3306` (05) |
| Auth Service URL for containers | `http://host.docker.internal:8001/api/auth/verify-token` (05: reachable, answers 401 to a request without a token) |
| No shared network assumed | `docker-compose.yml` declares no external network. `host.docker.internal` reaches the port the Auth Service publishes on this machine; `extra_hosts: host-gateway` makes the name work on Linux too |
| Explicit shared network (optional) | `docker-compose.auth-network.yml` joins the Auth Service's network as `external` and calls `auth-service:8001` (11) |
| Migrations before start | Container command: wait for the database, then `alembic upgrade head`, then start the server; each step only if the previous one succeeded (06: `Cmd`, 04 and 10: logs) |
| No `.env` or secrets in the image | `.dockerignore` excludes `.env`, `.env.*` and more; the `Dockerfile` copies only `requirements.txt`, `app/`, `alembic/`, `alembic.ini`. Scan: 0 secret values in 9,279 image files and the build history (07) |
| Port exposed | `EXPOSE 8006`; published as `127.0.0.1:8006->8006/tcp` (03) |
| `/health` and `/docs` inside the container | 05: `/health` 200, `/health/db` 200, `/docs` 200 Swagger UI, `/openapi.json` 200 |

## 2. Instructions

### First run

```powershell
cd C:\Users\Administrator\ShopEase\shopease-product-catalog-service
Copy-Item .env.example .env        # first time only; replace every change-me value
docker compose up --build -d       # builds the image, starts MySQL, waits, migrates, starts the API
docker compose ps                  # both services "Up ... (healthy)"
docker compose logs                # add -f to follow, or a service name: docker compose logs catalog-service
```

Then open http://127.0.0.1:8006/docs.

The Authentication Service is a separate Compose project (`shopease-auth-service`). Start it there.
It must publish port 8001 on this machine, which its own `docker-compose.yml` does. Browsing works
without it; requests that carry a token answer 503 while it is unreachable.

### Stop and start again

```powershell
docker compose down                # removes the containers and the network; KEEPS the database volume
docker compose up -d               # same data as before
```

**Never add `-v`** (`docker compose down -v`): that deletes the `catalog_mysql_data` volume, and
with it every database inside, including `shopease_product_catalog_db`.

### Migrations

They run automatically on every container start (`alembic upgrade head`; nothing happens when the
database is already up to date). A failed migration stops the container before the API opens its
port. To run them by hand, or to see the current revision, use the running container:

```powershell
docker compose exec catalog-service alembic current
docker compose exec catalog-service alembic upgrade head
```

Downgrades drop tables and data: run them only against `shopease_product_catalog_test_db` (see the
project README).

### Options

```powershell
# Reach MySQL from this machine (127.0.0.1:3310) for Alembic, pytest or the seed script:
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

# Reach the Auth Service over a shared Docker network instead of host.docker.internal
# (the Auth Service stack must be running; its network is joined, never created or removed):
docker compose -f docker-compose.yml -f docker-compose.auth-network.yml up -d --build
```

Use the same `-f` options with `down`.

### Check inside the container

```powershell
docker compose exec catalog-service python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8006/health').read().decode())"
docker compose exec catalog-service python -c "import urllib.request as u; r = u.urlopen('http://127.0.0.1:8006/docs'); print(r.status, 'swagger-ui' in r.read().decode())"
```

The fuller check used for file 05 (run as `docker compose exec -T catalog-service python - < check.py`):

```python
import json, os, urllib.request, urllib.error
base = "http://127.0.0.1:%s" % os.environ["SERVICE_PORT"]
def get(path, method="GET"):
    req = urllib.request.Request(base + path if path.startswith("/") else path, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.headers.get("content-type"), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type"), e.read().decode()
for path in ("/health", "/health/db"):
    status, ctype, body = get(path)
    print(f"GET {path} -> {status} {ctype}\n  {body}")
status, ctype, body = get("/docs")
print(f"GET /docs -> {status} {ctype}\n  <title>: {body.split('<title>')[1].split('</title>')[0]}\n  loads Swagger UI: {'swagger-ui' in body}, points to: {body.split('url: ')[1].split(',')[0] if 'url: ' in body else '?'}")
status, ctype, body = get("/openapi.json")
spec = json.loads(body)
print(f"GET /openapi.json -> {status}; title {spec['info']['title']!r}, version {spec['info']['version']}, {len(spec['paths'])} paths")
url = os.environ["AUTH_SERVICE_VERIFY_URL"]
status, ctype, body = get(url, method="POST")
print(f"POST {url} (no token, straight from this container) -> {status}\n  {body}")
```

### Check for secrets in the image

```powershell
python -m scripts.docker_secret_scan       # searches the image and this folder for the values in .env
```

## 3. Evidence files

| File | Command(s) | Result |
|---|---|---|
| `01_environment_and_state_before.txt` | `docker version`, `docker compose version`, volume and database state | Docker 29.6.2, Compose v5.3.1; volume from 2026-11-11; `shopease_product_catalog_db` at `c4a7d2e91b30` |
| `02_compose_up_build.log` | `docker compose up --build -d` | Image built; MySQL `Healthy` before the API `Started`; exit code 0 |
| `03_compose_ps.txt` | `docker compose ps` | Both `Up (healthy)`; API on `127.0.0.1:8006`, MySQL not published |
| `04_compose_logs.log` | `docker compose logs` | API: database ready → Alembic → Uvicorn on 0.0.0.0:8006 → health checks 200 |
| `05_checks_inside_container.txt` | `docker compose exec catalog-service ...` | `/health`, `/health/db`, `/docs`, `/openapi.json` all 200; Auth Service reachable (401 without a token); user `app`; no `.env`; `alembic current` = head |
| `06_image_mysql_and_host_checks.txt` | `docker image inspect`, `docker inspect`, `curl` | No secret in the image's settings; MySQL healthy; named volume mounted; from this machine `/health` and `/docs` 200; a forged token is refused by the real Auth Service (401) |
| `07_secret_scan.txt` | `python -m scripts.docker_secret_scan` | 0 matches in the build history, 9,279 image files and this folder; no `.env` in the image |
| `08_wait_for_mysql.log` | MySQL stopped, then started, while the wait step runs | Gives up after the timeout (exit 1) when MySQL is down; retries and succeeds (exit 0) when it comes up |
| `09_compose_down.log` | `docker compose down` | Containers and network removed; volume `catalog_mysql_data` still listed, same creation date |
| `10_restart_data_persisted.txt` | `docker compose up -d`, same database query as 01 | Identical: all three databases, migration versions and the service user survived |
| `11_shared_network_option.txt` | Up and down with `docker-compose.auth-network.yml` | API on both networks, MySQL only on its own; Auth Service reached as `auth-service:8001`; its network left in place after `down` |

## 4. Notes

- **What the persistence check shows.** `shopease_product_catalog_db` holds no rows at present. The
  check therefore shows that the volume kept the databases, their migration state and the service
  user. A re-initialised volume would have none of them.
- **The `docker compose ps` table** prints `<no value>` as the header of the health column; that is
  how Compose v5.3.1 labels `{{.Health}}`. The values below it are correct.
- **`docker compose port catalog-mysql 3306`** answers `invalid IP:0`: the port is not published.
  `docker compose ps` shows the same (`3306/tcp` without a host address).
- **The `GPG_KEY` setting in the image** is the official Python image's public release-signing key
  ID, not a secret.
- **What was done to the stack.** All runs used the existing volume, and no volume was removed.
  Afterwards the stack was started again with `docker-compose.dev.yml`, as it was before the task.
  That was needed for the MySQL test runs.
