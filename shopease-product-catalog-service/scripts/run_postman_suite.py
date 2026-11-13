"""Run the Postman collection with Newman and record the results (Task 11).

    python -m scripts.run_postman_suite --newman PATH_TO_NEWMAN [--screenshots PATH_TO_NODE_SCRIPT]

Run A, all 20 scenarios: a second Catalog Service instance (port 8016) on the MySQL test database
shopease_product_catalog_test_db, with the stand-in Authentication Service (port 8099), because
the live Authentication Service has no ADMIN account.
  1. Newman runs folders 00-19 and 20a in order.
  2. Folder 20b (one stock-out of 1 unit) runs in BURST separate Newman processes at the same time,
     against a product with stock 5.
  3. Newman runs 20c: stock 0, exactly 5 stock-outs, unbroken history.
  4. Optional: Swagger UI screenshots, with real requests, while both instances are up.
  5. Newman runs 99: the cleanup requests (deactivate the run's product and categories).
  6. The database rows of the run are checked directly in MySQL.
  7. The run's rows are deleted from the test database (and the deletion checked).

Run B, live: the running container (port 8006) with the real Authentication Service and its
configured database. Only folders that need no token: 06, 19 and L.

Reports go to DELIVERABELS/Test_Results/postman/. The stand-in tokens are removed from them.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import bindparam, create_engine, text

from app.core.config import get_settings

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "DELIVERABELS" / "Test_Results" / "postman"
COLLECTION = ROOT / "postman" / "ShopEase_Product_Catalog_Service.postman_collection.json"
TEST_DATABASE = "shopease_product_catalog_test_db"
AUTH_PORT, CATALOG_PORT, LIVE_URL = 8099, 8016, "http://127.0.0.1:8006"
BURST = 12
FOLDERS = [item["name"] for item in json.loads(COLLECTION.read_text(encoding="utf-8"))["item"]]
SEQUENTIAL = [name for name in FOLDERS if re.match(r"(0\d|1\d|20a) ", name)]  # 00 Setup to 20a, in order
BURST_FOLDER = "20b Simultaneous stock updates: one stock-out (run many at once)"
CONSISTENCY = "20c Simultaneous stock updates: verify consistency"
CLEANUP_FOLDER = "99 Cleanup (deactivate what this run created)"
LIVE = ["06 Retrieve product details using an invalid ID",
        "19 Access protected APIs without a JWT and with an invalid token", "L Live service: public reads"]


def log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def start(args: list[str], env: dict, logfile: Path) -> subprocess.Popen:
    return subprocess.Popen(args, cwd=ROOT, env=env, stdout=logfile.open("w", encoding="utf-8"),
                            stderr=subprocess.STDOUT)


def wait_for(url: str, seconds: int = 60) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"{url} did not answer within {seconds} s")


def newman(binary: str, env_file: Path, folders: list[str], name: str, *, export: Path | None = None,
           html: bool = True) -> dict:
    """Run Newman; returns the JSON report. CLI output is kept in NAME.txt."""
    report = OUT / f"{name}.json"
    reporters = "cli,json,htmlextra" if html else "json"
    cmd = [binary, "run", str(COLLECTION), "-e", str(env_file), "--reporters", reporters,
           "--reporter-json-export", str(report), "--color", "off", "--disable-unicode", "--timeout-request", "20000"]
    if html:
        cmd += ["--reporter-htmlextra-export", str(OUT / f"{name}.html"),
                "--reporter-htmlextra-skipHeaders", "Authorization",
                "--reporter-htmlextra-title", f"ShopEase Product Catalog: {name}"]
    for folder in folders:
        cmd += ["--folder", folder]
    if export:
        cmd += ["--export-environment", str(export)]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if html:
        (OUT / f"{name}.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    return json.loads(report.read_text(encoding="utf-8"))


def summary(report: dict) -> dict:
    stats = report["run"]["stats"]
    failures = [{"folder": f.get("parent", {}).get("name") if isinstance(f.get("parent"), dict) else None,
                 "request": f["source"]["name"], "test": f["error"].get("test") or f["error"].get("name"),
                 "message": f["error"]["message"]} for f in report["run"]["failures"]]
    return {"requests": stats["requests"]["total"], "requests_failed": stats["requests"]["failed"],
            "assertions": stats["assertions"]["total"], "assertions_failed": stats["assertions"]["failed"],
            "failures": failures}


def redact(path: Path, secrets: list[str]) -> None:
    content = path.read_text(encoding="utf-8")
    for secret in secrets:
        content = content.replace(secret, "<stand-in token removed>")
    path.write_text(content, encoding="utf-8")


def test_engine():
    return create_engine(get_settings().database_url.set(database=TEST_DATABASE), hide_parameters=True,
                         connect_args={"init_command": "SET time_zone = '+00:00'"})


def verify_database(run_id: str, *, with_swagger_product: bool) -> tuple[list[str], bool]:
    """Checks the run's rows directly in MySQL. Returns (report lines, all passed)."""
    prefix = f"PM{run_id}"
    lines, ok = [], True

    def check(title: str, passed: bool, detail: str) -> None:
        nonlocal ok
        ok &= passed
        lines.append(f"| {'PASS' if passed else 'FAIL'} | {title} | {detail} |")

    with test_engine().connect() as db:
        q = lambda sql, **p: db.execute(text(sql), p).all()  # noqa: E731
        products = q("SELECT p.id, p.sku, p.stock_quantity, p.is_active, p.category_id, c.name FROM products p "
                     "LEFT JOIN categories c ON c.id = p.category_id WHERE p.sku LIKE :s ORDER BY p.id", s=f"{prefix}-%")
        lines.append(f"Products of run {prefix}:\n\n| id | sku | stock | active | category |\n|---|---|---|---|---|")
        lines += [f"| {r.id} | {r.sku} | {r.stock_quantity} | {bool(r.is_active)} | {r.category_id} {r.name} |" for r in products]
        lines.append("\n| Result | Check | Detail |\n|---|---|---|")
        expected = {"MOB-1": (4, False), "HIDDEN": (1, False), "DEL-1": (2, False), "PHN-1": (12, True),
                    "MOB-2": (0, True), "LAP-1": (7, True), "CONC": (0, True)}
        expected_rows = {"MOB-1": 4, "HIDDEN": 1, "DEL-1": 1, "PHN-1": 1, "MOB-2": 0, "LAP-1": 1, "CONC": 6}
        if with_swagger_product:  # created in Swagger UI: initial stock 3, stock-in 10, refused stock-out
            expected["SWG-1"], expected_rows["SWG-1"] = (13, True), 2
        got = {r.sku.split("-", 1)[1]: (r.stock_quantity, bool(r.is_active)) for r in products}
        check("Exactly the products the scenarios created", got == expected,
              f"{len(got)} products; refused requests (duplicate SKU, invalid category, negative price, customer, "
              f"no token) created none")
        check("Every product's category exists (foreign key)", all(r.name is not None for r in products),
              "LEFT JOIN categories: no NULL")
        bad_chain = []
        for r in products:
            level = 0
            for t in q("SELECT transaction_type, quantity, previous_stock, updated_stock FROM inventory_transactions "
                       "WHERE product_id = :id ORDER BY id", id=r.id):
                sign = 1 if t.transaction_type == "IN" else -1
                if t.previous_stock != level or t.updated_stock != level + sign * t.quantity:
                    bad_chain.append(r.sku)
                level = t.updated_stock
            if level != r.stock_quantity:
                bad_chain.append(r.sku)
        check("Stock equals the replayed history, for every product", not bad_chain, f"broken: {bad_chain or 'none'}")
        counts = {r.sku.split('-', 1)[1]: r.n for r in q(
            "SELECT p.sku, COUNT(t.id) AS n FROM products p LEFT JOIN inventory_transactions t ON t.product_id = p.id "
            "WHERE p.sku LIKE :s GROUP BY p.sku", s=f"{prefix}-%")}
        check("History rows per product", counts == expected_rows,
              ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
        orphans = q("SELECT COUNT(*) AS n FROM inventory_transactions t LEFT JOIN products p ON p.id = t.product_id "
                    "WHERE p.id IS NULL")[0].n
        check("No inventory transaction without its product (whole test database)", orphans == 0, f"{orphans} orphans")
        dup_sku = q("SELECT COUNT(*) AS n FROM (SELECT UPPER(sku) FROM products GROUP BY UPPER(sku) HAVING COUNT(*) > 1) d")[0].n
        dup_cat = q("SELECT COUNT(*) AS n FROM (SELECT LOWER(name) FROM categories GROUP BY LOWER(name) HAVING COUNT(*) > 1) d")[0].n
        check("SKUs unique, ignoring case (whole test database)", dup_sku == 0, f"{dup_sku} duplicates")
        check("Category names unique, ignoring case (whole test database)", dup_cat == 0, f"{dup_cat} duplicates")
        negative = q("SELECT COUNT(*) AS n FROM products WHERE stock_quantity < 0")[0].n
        check("No negative stock (whole test database)", negative == 0, f"{negative} rows")
        cats = q("SELECT name, is_active FROM categories WHERE name LIKE :s ORDER BY id", s=f"{prefix} %")
        check("Categories of the run", [(c.name.split(' ', 1)[1], bool(c.is_active)) for c in cats] ==
              [("Phones", False), ("Laptops", False), ("Archive", False)],
              ", ".join(f"{c.name} active={bool(c.is_active)}" for c in cats))
        fks = q("SELECT TABLE_NAME, CONSTRAINT_NAME, REFERENCED_TABLE_NAME, DELETE_RULE FROM "
                "information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = :d ORDER BY 1", d=TEST_DATABASE)
        check("Foreign keys defined, ON DELETE RESTRICT", {(r[0], r[2], r[3]) for r in fks} ==
              {("products", "categories", "RESTRICT"), ("inventory_transactions", "products", "RESTRICT")},
              "; ".join(f"{r[0]}.{r[1]} -> {r[2]} ({r[3]})" for r in fks))
        checks = q("SELECT tc.TABLE_NAME, tc.CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS tc WHERE "
                   "tc.CONSTRAINT_SCHEMA = :d AND tc.CONSTRAINT_TYPE IN ('CHECK', 'UNIQUE') ORDER BY 1, 2", d=TEST_DATABASE)
        names = {r[1] for r in checks}
        needed = {"uq_products_sku", "uq_categories_name", "ck_products_price_non_negative",
                  "ck_products_stock_quantity_non_negative", "ck_products_discount_price_valid",
                  "ck_inventory_transactions_quantity_positive", "ck_inventory_transactions_stock_arithmetic"}
        check("Unique and CHECK constraints present", needed <= names, ", ".join(sorted(needed)))
    return lines, ok


def cleanup(run_id: str) -> str:
    prefix = f"PM{run_id}"
    with test_engine().begin() as db:
        ids = [r[0] for r in db.execute(text("SELECT id FROM products WHERE sku LIKE :s"), {"s": f"{prefix}-%"})]
        if ids:
            for table, column in (("inventory_transactions", "product_id"), ("products", "id")):
                statement = text(f"DELETE FROM {table} WHERE {column} IN :ids").bindparams(
                    bindparam("ids", expanding=True))
                db.execute(statement, {"ids": ids})
        db.execute(text("DELETE FROM categories WHERE name LIKE :s"), {"s": f"{prefix} %"})
    with test_engine().connect() as db:
        left = (db.execute(text("SELECT COUNT(*) FROM products WHERE sku LIKE :s"), {"s": f"{prefix}-%"}).scalar(),
                db.execute(text("SELECT COUNT(*) FROM categories WHERE name LIKE :s"), {"s": f"{prefix} %"}).scalar())
    return f"Deleted {len(ids)} products with their history and the run's categories; left: products {left[0]}, categories {left[1]}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--newman", required=True)
    parser.add_argument("--screenshots", help="node script that takes the Swagger UI screenshots")
    parser.add_argument("--node", default="node")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    run_id = str(int(time.time()))[-9:]
    from scripts.stand_in_auth_service import issue_token
    admin, customer = issue_token("ADMIN"), issue_token("USER")

    env = dict(os.environ, PYTHONPATH=str(ROOT))
    catalog_env = dict(env, SERVICE_HOST="127.0.0.1", SERVICE_PORT=str(CATALOG_PORT), MYSQL_DATABASE=TEST_DATABASE,
                       AUTH_SERVICE_VERIFY_URL=f"http://127.0.0.1:{AUTH_PORT}/api/auth/verify-token",
                       LOG_LEVEL="WARNING")
    auth_proc = start([sys.executable, "-m", "uvicorn", "scripts.stand_in_auth_service:app", "--host", "127.0.0.1",
                       "--port", str(AUTH_PORT), "--log-level", "warning"], env, OUT / "standin_auth_service.log")
    catalog_proc = start([sys.executable, "-m", "app"], catalog_env, OUT / "standin_catalog_instance.log")
    results: dict = {"run_id": run_id, "started": started.isoformat(timespec="seconds")}
    try:
        wait_for(f"http://127.0.0.1:{AUTH_PORT}/docs")
        wait_for(f"http://127.0.0.1:{CATALOG_PORT}/health")
        log(f"Run A: instance on {CATALOG_PORT} (test database), stand-in auth on {AUTH_PORT}, run_id {run_id}")
        env_file = OUT / "_env_standin.json"
        env_file.write_text(json.dumps({"name": "stand-in run", "values": [
            {"key": "base_url", "value": f"http://127.0.0.1:{CATALOG_PORT}"},
            {"key": "admin_token", "value": admin}, {"key": "customer_token", "value": customer},
            {"key": "run_id", "value": run_id}]}), encoding="utf-8")
        exported = OUT / "_env_after_sequential.json"
        results["A1 sequential"] = summary(newman(args.newman, env_file, SEQUENTIAL, "A1_scenarios_01_to_20a",
                                                  export=exported))
        log(f"A1: {results['A1 sequential']['assertions']} assertions, {results['A1 sequential']['assertions_failed']} failed")

        burst_dir = OUT / "A2_burst"
        burst_dir.mkdir(exist_ok=True)
        with ThreadPoolExecutor(BURST) as pool:
            reports = list(pool.map(lambda i: newman(args.newman, exported, [BURST_FOLDER], f"A2_burst/run_{i:02d}",
                                                     html=False), range(BURST)))
        codes = [r["run"]["executions"][0]["response"]["code"] for r in reports]
        first = min(r["run"]["timings"]["started"] for r in reports)
        timeline = sorted((r["run"]["timings"]["started"] - first, r["run"]["timings"]["completed"] - first,
                           r["run"]["executions"][0]["response"]["code"],
                           r["run"]["executions"][0]["response"]["responseTime"]) for r in reports)
        (burst_dir / "timeline.txt").write_text(
            f"{BURST} Newman processes started together, each sending one stock-out of 1 unit (stock was 5).\n"
            "Times in ms from the first process start (run start/end per process; response = request time).\n\n"
            + "\n".join(f"run start +{a:5d}  run end +{b:5d}  status {c}  response {d} ms" for a, b, c, d in timeline)
            + "\n", encoding="utf-8")
        results["A2 burst"] = {"processes": BURST, "status_codes": sorted(codes),
                               "201": codes.count(201), "409": codes.count(409),
                               "assertions_failed": sum(r["run"]["stats"]["assertions"]["failed"] for r in reports)}
        log(f"A2: {BURST} simultaneous Newman processes -> {results['A2 burst']['201']} x 201, {results['A2 burst']['409']} x 409")

        results["A3 verify"] = summary(newman(args.newman, exported, [CONSISTENCY], "A3_scenario_20c_consistency"))
        log(f"A3: {results['A3 verify']['assertions']} assertions, {results['A3 verify']['assertions_failed']} failed")

        screenshots_ok = False
        if args.screenshots:
            shot_env = dict(env, LIVE_URL=LIVE_URL, STANDIN_URL=f"http://127.0.0.1:{CATALOG_PORT}",
                            STANDIN_ADMIN_TOKEN=admin, RUN_ID=run_id,
                            OUT_DIR=str(ROOT / "DELIVERABELS" / "screenshots"))
            shot = subprocess.run([args.node, args.screenshots], cwd=ROOT, env=shot_env, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace")
            (OUT / "A4_screenshots.log").write_text(shot.stdout + shot.stderr, encoding="utf-8")
            screenshots_ok = shot.returncode == 0
            results["A4 screenshots"] = "exit code %d" % shot.returncode
            log(f"A4 screenshots: {results['A4 screenshots']}")

        results["A5 cleanup requests"] = summary(newman(args.newman, exported, [CLEANUP_FOLDER], "A5_cleanup_requests"))
        log(f"A5: {results['A5 cleanup requests']['assertions']} assertions, "
            f"{results['A5 cleanup requests']['assertions_failed']} failed")

        lines, db_ok = verify_database(run_id, with_swagger_product=screenshots_ok)
        results["A6 database"] = "PASS" if db_ok else "FAIL"
        (OUT / "A6_database_verification.md").write_text(
            f"# Database verification, run {run_id}\n\nQueried directly in MySQL ({TEST_DATABASE}) after the "
            f"Newman runs and the Swagger UI requests, before the rows were deleted.\n\n"
            + "\n".join(lines) + "\n", encoding="utf-8")
        log(f"A6 database checks: {results['A6 database']}")
    finally:
        try:
            results["A7 delete run rows"] = cleanup(run_id)
            log(results["A7 delete run rows"])
        finally:
            for proc in (catalog_proc, auth_proc):
                proc.terminate()
                proc.wait(timeout=20)

    log("Run B: live container, real Authentication Service")
    live_env = OUT / "_env_live.json"
    live_env.write_text(json.dumps({"name": "live", "values": [
        {"key": "base_url", "value": LIVE_URL}, {"key": "admin_token", "value": ""},
        {"key": "customer_token", "value": ""}, {"key": "run_id", "value": run_id}]}), encoding="utf-8")
    results["B live"] = summary(newman(args.newman, live_env, LIVE, "B_live_container"))
    log(f"B: {results['B live']['assertions']} assertions, {results['B live']['assertions_failed']} failed")

    for path in list(OUT.glob("*.json")) + list(OUT.glob("*.html")) + list(OUT.glob("*.txt")) + list(OUT.glob("*.log")) + list(OUT.glob("*.md")) + list((OUT / "A2_burst").glob("*.json")):
        redact(path, [admin, customer])
    for temp in OUT.glob("_env_*.json"):
        temp.unlink()
    results["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (OUT / "summary.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    failed = (results["A1 sequential"]["assertions_failed"] + results["A2 burst"]["assertions_failed"]
              + results["A3 verify"]["assertions_failed"] + results["A5 cleanup requests"]["assertions_failed"]
              + results["B live"]["assertions_failed"])
    log(f"Done: {failed} failed assertions in total; database checks {results['A6 database']}")
    return 0 if failed == 0 and results["A6 database"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
