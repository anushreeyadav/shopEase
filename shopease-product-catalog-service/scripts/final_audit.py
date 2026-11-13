"""Final project audit (Task 12). Read-only: it creates, changes and deletes nothing.

    python -m scripts.final_audit        (stack running with docker-compose.dev.yml, MySQL on 3310)

Writes DELIVERABELS/Test_Results/final_audit/03_final_audit.txt and
DELIVERABELS/Database_Evidence/schema_reference.sql (SHOW CREATE TABLE output, for reference only:
the tables are created by Alembic). Every check prints PASS, FAIL or INFO with what was observed.
Secret values from .env are searched for but never printed.
"""

import datetime as dt
import subprocess
import sys
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text

from app.core.config import get_settings

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "DELIVERABELS" / "Test_Results" / "final_audit" / "03_final_audit.txt"
SCHEMA = ROOT / "DELIVERABELS" / "Database_Evidence" / "schema_reference.sql"
BASE = "http://127.0.0.1:8006"
AUTH_VERIFY = "http://127.0.0.1:8001/api/auth/verify-token"
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml"]
# The Postman collection's forged_token: claims ADMIN, signed with a random key that was thrown
# away, so no service can accept it.
FORGED = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwicm9sZSI6IkFETUlOIiwiaWF0IjoxNzAwMDAw"
          "MDAwLCJleHAiOjQxMDAwMDAwMDB9.4ACUJLouI-yOP8kAKmzlGscota9QQ5cnq1zTsVfU2Hc")

EXPECTED_ROUTES = {
    ("GET", "/"), ("GET", "/health"), ("GET", "/health/db"),
    ("GET", "/api/categories/"), ("POST", "/api/categories/"),
    ("GET", "/api/categories/{category_id}"), ("PUT", "/api/categories/{category_id}"),
    ("PATCH", "/api/categories/{category_id}"), ("DELETE", "/api/categories/{category_id}"),
    ("GET", "/api/products/"), ("POST", "/api/products/"),
    ("GET", "/api/products/{product_id}"), ("PUT", "/api/products/{product_id}"),
    ("PATCH", "/api/products/{product_id}"), ("DELETE", "/api/products/{product_id}"),
    ("GET", "/api/inventory/{product_id}"), ("POST", "/api/inventory/{product_id}/stock-in"),
    ("POST", "/api/inventory/{product_id}/stock-out"), ("GET", "/api/inventory/{product_id}/history"),
    ("GET", "/api/inventory/low-stock"),
}

lines: list[str] = []
failures = 0


def say(line: str = "") -> None:
    lines.append(line)
    print(line)


def check(name: str, ok: bool, observed: str) -> None:
    global failures
    failures += not ok
    say(f"[{'PASS' if ok else 'FAIL'}] {name}: {observed}")


def run(cmd: list[str]) -> tuple[int, str]:
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return done.returncode, (done.stdout + done.stderr).strip()


def section(title: str) -> None:
    say()
    say(f"== {title} ==")


def endpoints() -> None:
    section("1. Required endpoints (live container, port 8006)")
    spec = httpx.get(f"{BASE}/openapi.json", timeout=10).json()
    found = {(m.upper(), p) for p, ops in spec["paths"].items() for m in ops}
    check("every required route is published", EXPECTED_ROUTES <= found,
          f"{len(EXPECTED_ROUTES & found)} of {len(EXPECTED_ROUTES)} present; missing {sorted(EXPECTED_ROUTES - found) or 'none'}")
    check("no unexpected route", found <= EXPECTED_ROUTES, f"extra {sorted(found - EXPECTED_ROUTES) or 'none'}")
    probes = [
        ("GET", "/health", 200), ("GET", "/health/db", 200), ("GET", "/docs", 200),
        ("GET", "/api/categories/", 200), ("GET", "/api/products/", 200),
        ("GET", "/api/products/?search=mobile&min_price=1000&max_price=5000&sort_by=price&sort_order=asc&page=1&page_size=10", 200),
        ("GET", "/api/products/999999", 404), ("GET", "/api/products/abc", 422),
        ("POST", "/api/categories/", 401), ("POST", "/api/products/", 401),
        ("PATCH", "/api/products/1", 401), ("DELETE", "/api/products/1", 401),
        ("GET", "/api/inventory/1", 401), ("POST", "/api/inventory/1/stock-in", 401),
        ("POST", "/api/inventory/1/stock-out", 401), ("GET", "/api/inventory/1/history", 401),
        ("GET", "/api/inventory/low-stock", 401),
    ]
    for method, path, expected in probes:
        got = httpx.request(method, BASE + path, json={} if method in ("POST", "PATCH") else None, timeout=10).status_code
        check(f"{method} {path} without a token", got == expected, f"{got} (expected {expected})")


def migrations() -> None:
    section("2. Database migration")
    _, heads = run([sys.executable, "-m", "alembic", "heads"])
    say(f"[INFO] alembic heads: {heads}")
    code, current = run(COMPOSE + ["exec", "-T", "catalog-service", "alembic", "current"])
    check("configured database (inside the container), alembic current", code == 0 and "(head)" in current,
          next((l for l in current.splitlines() if "(head)" in l), current[-200:]))
    code, out = run([sys.executable, "-m", "alembic", "check"])
    check("configured database, alembic check (models match the database)", code == 0,
          next((l for l in out.splitlines() if "No new upgrade" in l), out[-200:]))
    engine = create_engine(get_settings().database_url)
    with engine.connect() as conn:
        db = conn.execute(text("SELECT DATABASE()")).scalar()
        tables = sorted(r[0] for r in conn.execute(text("SHOW TABLES")))
        check("tables in " + db, tables == ["alembic_version", "categories", "inventory_transactions", "products"],
              ", ".join(tables))
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        check("alembic_version row", version == "c4a7d2e91b30", version)
        for table in ("categories", "products", "inventory_transactions"):
            say(f"[INFO] rows in {table}: {conn.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar()}")
        fks = conn.execute(text(
            "SELECT TABLE_NAME, REFERENCED_TABLE_NAME, DELETE_RULE FROM information_schema.REFERENTIAL_CONSTRAINTS "
            "WHERE CONSTRAINT_SCHEMA = DATABASE() ORDER BY TABLE_NAME")).all()
        check("foreign keys", [tuple(r) for r in fks] == [("inventory_transactions", "products", "RESTRICT"),
                                                          ("products", "categories", "RESTRICT")],
              "; ".join(f"{a} -> {b} ON DELETE {c}" for a, b, c in fks))
        checks = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.CHECK_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = DATABASE()")).scalar()
        check("CHECK constraints (categories 1, products 5, inventory_transactions 5)", checks == 11, f"{checks}")
        ddl = [conn.execute(text(f"SHOW CREATE TABLE {t}")).one()[1] for t in ("categories", "products", "inventory_transactions")]
        mysql_version = conn.execute(text("SELECT VERSION()")).scalar()
    SCHEMA.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA.write_text(
        f"-- SHOW CREATE TABLE output from MySQL {mysql_version}, database {db}, at Alembic revision {version}.\n"
        f"-- Captured {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M:%S} UTC by scripts/final_audit.py.\n"
        "-- REFERENCE ONLY. The tables are created and changed by Alembic (alembic upgrade head);\n"
        "-- do not run this file to create them.\n\n" + ";\n\n".join(ddl) + ";\n", encoding="utf-8")
    say(f"[INFO] schema reference written: {SCHEMA.relative_to(ROOT)}")


def jwt() -> None:
    section("3. JWT integration with the running Authentication Service (no account used)")
    got = httpx.get("http://127.0.0.1:8001/health", timeout=10).status_code
    check("Authentication Service /health", got == 200, str(got))
    got = httpx.post(AUTH_VERIFY, timeout=10).status_code
    check("Auth Service verify-token without a token", got == 401, str(got))
    got = httpx.post(AUTH_VERIFY, headers={"Authorization": f"Bearer {FORGED}"}, timeout=10).status_code
    check("Auth Service verify-token with a forged ADMIN token", got == 401, str(got))
    r = httpx.post(f"{BASE}/api/products/", json={}, headers={"Authorization": f"Bearer {FORGED}"}, timeout=10)
    check("Catalog POST /api/products/ with the forged token (decided by the real Auth Service)",
          r.status_code == 401 and r.headers.get("www-authenticate") == "Bearer", f"{r.status_code} {r.text}")
    code, env = run(COMPOSE + ["exec", "-T", "catalog-service", "printenv", "AUTH_SERVICE_VERIFY_URL"])
    say(f"[INFO] AUTH_SERVICE_VERIFY_URL in the container: {env}")
    say("[INFO] Not checked live: a real ADMIN token and a real USER token. The Authentication Service "
        "has no ADMIN account and no password was available (see the API testing report).")


def docker() -> None:
    section("4. Docker Compose")
    code, ps = run(COMPOSE + ["ps", "--format", "{{.Service}}\t{{.State}}\t{{.Status}}\t{{.Ports}}"])
    say(ps)
    check("both containers running and healthy", code == 0 and ps.count("(healthy)") == 2, f"{ps.count('(healthy)')} healthy")
    code, vols = run(["docker", "volume", "ls", "--format", "{{.Name}}"])
    check("named volume present", "shopease-product-catalog-service_catalog_mysql_data" in vols.split(),
          "shopease-product-catalog-service_catalog_mysql_data")
    code, out = run(COMPOSE + ["exec", "-T", "catalog-service", "sh", "-c", "ls -a /app; test -e /app/.env && echo ENV_PRESENT || echo no .env"])
    check(".env not in the running image", code == 0 and "no .env" in out, out.splitlines()[-1])


def secrets_and_files() -> None:
    section("5. Secrets and .env in the deliverables")
    values = []
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            if any(w in name for w in ("PASSWORD", "SECRET", "KEY")) and len(value.strip()) >= 8:
                values.append(value.strip().encode())
    say(f"[INFO] secret values read from .env: {len(values)} (never printed)")
    for folder in ("DELIVERABELS", "postman", "README.md", "app", "alembic", "tests", "scripts",
                   "Dockerfile", "docker-compose.yml", "docker-compose.dev.yml", "docker-compose.auth-network.yml",
                   ".env.example", "alembic.ini"):
        path = ROOT / folder
        files = [p for p in ([path] if path.is_file() else path.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
        hits = [p for p in files if any(v in p.read_bytes() for v in values)]
        check(f"no secret value in {folder}", not hits, f"{len(files)} files searched, {len(hits)} with a match"
              + (f": {[str(p.relative_to(ROOT)) for p in hits]}" if hits else ""))
    env_files = [p for p in ROOT.rglob(".env*") if ".venv" not in p.parts]
    check("only .env (local, ignored) and .env.example exist", sorted(p.name for p in env_files) == [".env", ".env.example"],
          ", ".join(str(p.relative_to(ROOT)) for p in env_files))
    in_deliverables = [p for p in (ROOT / "DELIVERABELS").rglob(".env*")]
    check("no .env file inside DELIVERABELS", not in_deliverables, f"{len(in_deliverables)} found")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    check(".env listed in .gitignore and .dockerignore", ".env" in gitignore and ".env" in dockerignore, "yes")
    logs = list((ROOT / "DELIVERABELS").rglob("*.log"))
    kept = "!DELIVERABELS/**/*.log" in gitignore
    check(f"{len(logs)} evidence .log files in DELIVERABELS not ignored by Git ('*.log' rule with the "
          "'!DELIVERABELS/**/*.log' exception)", kept or "*.log" not in gitignore,
          "exception present" if kept else "no '*.log' rule")


def git() -> None:
    section("6. Git (no Git command is run by this script)")
    own = (ROOT / ".git").exists()
    check("this folder has no .git directory of its own", not own, "absent" if not own else "present")
    say("[INFO] The folder sits inside the parent ShopEase repository. Whether anything was committed or pushed "
        "can only be confirmed with Git; this script does not run Git (see the completion report).")


def main() -> int:
    say(f"# Final audit, {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M:%S} UTC, python -m scripts.final_audit")
    for step in (endpoints, migrations, jwt, docker, secrets_and_files, git):
        try:
            step()
        except Exception as exc:  # record the failure and continue with the other checks
            check(step.__name__, False, f"{type(exc).__name__}: {exc}")
    say()
    say(f"Result: {failures} check(s) failed")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
