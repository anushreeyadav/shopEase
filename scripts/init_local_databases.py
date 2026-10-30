"""Create the five ShopEase databases and their per-service MySQL users on a local server.

Safe to re-run: it only uses CREATE ... IF NOT EXISTS and GRANT. It never drops,
truncates or alters existing databases, and never changes an existing user's password.
Docker Compose does the same through deploy/mysql/init/01-create-databases.sh.

    python scripts/init_local_databases.py --dry-run   # print the SQL (passwords masked)
    python scripts/init_local_databases.py             # execute it

Credentials come from the environment, then from .env in the current directory:
  MYSQL_HOST, MYSQL_PORT                 server to initialize
  MYSQL_ADMIN_USER, MYSQL_ADMIN_PASSWORD an account allowed to create databases and users
  <SVC>_DB_NAME, <SVC>_DB_USER, <SVC>_DB_PASSWORD,
  <SVC>_DB_MIGRATION_USER, <SVC>_DB_MIGRATION_PASSWORD   for SVC in AUTH USER PRODUCT ORDER PAYMENT
"""

import argparse
import os
import re
import sys
from pathlib import Path

SERVICES = ["AUTH", "USER", "PRODUCT", "ORDER", "PAYMENT"]
RUNTIME_PRIVILEGES = "SELECT, INSERT, UPDATE, DELETE"
MIGRATION_PRIVILEGES = "SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES"
PLACEHOLDERS = {"", "change-me"}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]{1,32}$")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    values.update(os.environ)
    return values


def statements(env: dict[str, str]) -> list[tuple[str, tuple[str, ...]]]:
    """(sql, params) pairs. Identifiers are validated; passwords are bound parameters."""
    result = []
    for svc in SERVICES:
        db = env[f"{svc}_DB_NAME"]
        users = [
            (env[f"{svc}_DB_USER"], env[f"{svc}_DB_PASSWORD"], RUNTIME_PRIVILEGES),
            (env[f"{svc}_DB_MIGRATION_USER"], env[f"{svc}_DB_MIGRATION_PASSWORD"], MIGRATION_PRIVILEGES),
        ]
        for name in [db, *(u for u, _, _ in users)]:
            if not _IDENTIFIER.match(name):
                raise SystemExit(f"Refusing unsafe identifier: {name!r}")
        result.append(
            (f"CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci", ())
        )
        for user, password, privileges in users:
            result.append((f"CREATE USER IF NOT EXISTS '{user}'@'%%' IDENTIFIED BY %s", (password,)))
            result.append((f"GRANT {privileges} ON `{db}`.* TO '{user}'@'%%'", ()))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print the SQL without connecting")
    parser.add_argument("--env-file", default=".env", type=Path)
    args = parser.parse_args()

    env = load_env(args.env_file)
    missing = [
        f"{svc}_DB_{k}" for svc in SERVICES
        for k in ("NAME", "USER", "PASSWORD", "MIGRATION_USER", "MIGRATION_PASSWORD")
        if f"{svc}_DB_{k}" not in env
    ]
    if missing:
        raise SystemExit("Missing settings: " + ", ".join(missing))
    weak = [f"{svc}_DB_{k}" for svc in SERVICES for k in ("PASSWORD", "MIGRATION_PASSWORD")
            if env[f"{svc}_DB_{k}"] in PLACEHOLDERS]
    if weak and not args.dry_run:
        raise SystemExit("Replace placeholder passwords first: " + ", ".join(weak))

    plan = statements(env)
    if args.dry_run:
        for sql, params in plan:
            print((sql % tuple("'***'" for _ in params)).replace("%%", "%") + ";")
        return 0

    import pymysql  # installed with every service

    connection = pymysql.connect(
        host=env.get("MYSQL_HOST", "localhost"),
        port=int(env.get("MYSQL_PORT", "3306")),
        user=env.get("MYSQL_ADMIN_USER", "root"),
        password=env.get("MYSQL_ADMIN_PASSWORD", ""),
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            for sql, params in plan:
                # Always pass a tuple: PyMySQL only turns %% into % when params are given.
                cursor.execute(sql, params)
    finally:
        connection.close()
    print(f"Initialized {len(SERVICES)} databases and {2 * len(SERVICES)} users "
          f"on {env.get('MYSQL_HOST', 'localhost')}:{env.get('MYSQL_PORT', '3306')}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
