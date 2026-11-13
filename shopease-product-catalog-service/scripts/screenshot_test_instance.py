"""Start the test instance for manual screenshots of ADMIN and customer operations (Task 12).

    python -m scripts.screenshot_test_instance            start, print tokens, wait for Enter, then clean up
    python -m scripts.screenshot_test_instance --check    start, check both tokens work, clean up, exit
    python -m scripts.screenshot_test_instance --run CMD  start, run CMD with TEST_URL, TEST_ADMIN_TOKEN and
                                                          TEST_USER_TOKEN in its environment, clean up, exit
                                                          (used by scripts/take_submission_screenshots.py)

Why: the live Authentication Service has no ADMIN account, so ADMIN screenshots (category and
product creation, stock-in, ...) cannot be taken on the live service. This starts, on this machine:

  - the stand-in Authentication Service (scripts/stand_in_auth_service.py) on 127.0.0.1:8099,
  - a second Catalog Service instance (same code, python -m app) on 127.0.0.1:8016, using the MySQL
    TEST database shopease_product_catalog_test_db (never the configured database),

and prints an ADMIN token and a customer (USER) token that only the stand-in accepts. Open
http://127.0.0.1:8016/docs, click Authorize and paste a token. Label these screenshots as
"test instance, stand-in Authentication Service".

Needs MySQL on 127.0.0.1:3310 (docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d).
On exit, rows created while it ran (IDs above those present at start) are deleted from the test
database only; earlier rows are not touched. The live container and the real Authentication Service
are not used or changed.
"""

import argparse
import os
import subprocess
import sys
import time

import httpx
from sqlalchemy import text

from scripts.run_postman_suite import TEST_DATABASE, test_engine, wait_for
from scripts.stand_in_auth_service import issue_token

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTH_PORT, CATALOG_PORT = 8099, 8016
TABLES = ("inventory_transactions", "products", "categories")  # delete order (foreign keys)


def max_ids(engine) -> dict[str, int]:
    with engine.connect() as conn:
        assert conn.execute(text("SELECT DATABASE()")).scalar() == TEST_DATABASE
        return {t: conn.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {t}")).scalar() for t in TABLES}


def delete_new_rows(engine, start: dict[str, int]) -> dict[str, int]:
    deleted = {}
    with engine.begin() as conn:
        assert conn.execute(text("SELECT DATABASE()")).scalar() == TEST_DATABASE
        new_products = f"SELECT id FROM products WHERE id > {start['products']}"
        # Transactions of new products, and new transactions of older products.
        deleted["inventory_transactions"] = conn.execute(text(
            f"DELETE FROM inventory_transactions WHERE id > {start['inventory_transactions']} "
            f"OR product_id IN ({new_products})")).rowcount
        deleted["products"] = conn.execute(text(f"DELETE FROM products WHERE id > {start['products']}")).rowcount
        deleted["categories"] = conn.execute(text(f"DELETE FROM categories WHERE id > {start['categories']}")).rowcount
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="check the tokens work, then stop")
    parser.add_argument("--run", nargs=argparse.REMAINDER, help="command to run while the instance is up")
    args = parser.parse_args()

    engine = test_engine()
    start = max_ids(engine)
    env = dict(os.environ, PYTHONPATH=ROOT)
    catalog_env = dict(env, SERVICE_HOST="127.0.0.1", SERVICE_PORT=str(CATALOG_PORT), MYSQL_DATABASE=TEST_DATABASE,
                       AUTH_SERVICE_VERIFY_URL=f"http://127.0.0.1:{AUTH_PORT}/api/auth/verify-token")
    procs = [
        subprocess.Popen([sys.executable, "-m", "uvicorn", "scripts.stand_in_auth_service:app", "--host", "127.0.0.1",
                          "--port", str(AUTH_PORT), "--log-level", "warning"], cwd=ROOT, env=env),
        subprocess.Popen([sys.executable, "-m", "app"], cwd=ROOT, env=catalog_env),
    ]
    code = 0
    try:
        wait_for(f"http://127.0.0.1:{AUTH_PORT}/docs")
        wait_for(f"http://127.0.0.1:{CATALOG_PORT}/health")
        admin, customer = issue_token("ADMIN"), issue_token("USER")
        url = f"http://127.0.0.1:{CATALOG_PORT}"
        if args.check:
            got = {who: httpx.get(f"{url}/api/inventory/low-stock", headers={"Authorization": f"Bearer {tok}"},
                                  timeout=10).status_code for who, tok in (("ADMIN", admin), ("USER", customer))}
            print(f"low-stock report: ADMIN token -> {got['ADMIN']} (expected 200), "
                  f"USER token -> {got['USER']} (expected 403)")
            code = 0 if got == {"ADMIN": 200, "USER": 403} else 1
        elif args.run:
            code = subprocess.run(args.run, cwd=ROOT, env=dict(os.environ, TEST_URL=url, TEST_ADMIN_TOKEN=admin,
                                                               TEST_USER_TOKEN=customer)).returncode
        else:
            print(f"\nTest instance: {url}/docs   (database {TEST_DATABASE}, stand-in Authentication Service)")
            print("Tokens are valid for 30 minutes and are accepted ONLY by the stand-in. Do not put them in reports.")
            print(f"\nADMIN token:\n{admin}\n\nCustomer (USER) token:\n{customer}\n")
            input("Press Enter to stop and delete the rows created during this session... ")
    except KeyboardInterrupt:
        pass
    finally:
        for proc in procs:
            proc.terminate()
            proc.wait(timeout=20)
        time.sleep(1)
        print("deleted from the test database:", delete_new_rows(engine, start))
    return code


if __name__ == "__main__":
    sys.exit(main())
