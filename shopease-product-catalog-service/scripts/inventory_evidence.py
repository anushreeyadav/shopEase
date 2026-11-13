"""Record request/response evidence for the inventory API.

    $env:MYSQL_DATABASE = "shopease_product_catalog_test_db"
    python -m scripts.inventory_evidence DELIVERABELS/Test_Results/inventory_logs/02_inventory_transcript.md

Part A: the real application in-process, against the real MySQL test database, inside one
transaction that is rolled back at the end. Only the Authentication Service is a stand-in (the
live one has no ADMIN account). It includes a database failure injected on purpose, to show that
neither the stock nor the history changes when one of the two writes fails. Refuses any database
but the test one.

Part B: the running Catalog Service container with the real Authentication Service. Only
requests that must be refused are sent, so nothing is changed.

Simultaneous requests cannot be shown inside one rolled-back transaction; they are covered by
tests/test_inventory_concurrency.py (log: 01_pytest_inventory.log).
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import get_auth_client
from app.database.connection import engine, get_db
from app.main import app
from scripts.product_api_evidence import (
    ADMIN,
    CATALOG,
    CUSTOMER,
    TEST_DATABASE,
    bearer,
    lines,
    results,
    stand_in_auth,
    step,
    token,
)


def check(title: str, ok: bool, detail: str) -> None:
    results.append(ok)
    lines.append(f"Check, {title}: **{'PASS' if ok else 'FAIL'}**. {detail}\n")


def check_consistent(c, product_id: int, admin: dict) -> None:
    """Replays the full history and compares it with the current stock."""
    rows = c.get(f"/api/inventory/{product_id}/history", headers=admin, params={"page_size": 100}).json()["items"][::-1]
    stock, broken = 0, []
    for row in rows:
        sign = 1 if row["transaction_type"] == "IN" else -1
        if row["previous_stock"] != stock or row["updated_stock"] != stock + sign * row["quantity"]:
            broken.append(row["id"])
        stock = row["updated_stock"]
    current = c.get(f"/api/inventory/{product_id}", headers=admin).json()["stock_quantity"]
    chain = " → ".join(str(r["updated_stock"]) for r in rows)
    check("stock matches history", not broken and stock == current,
          f"{len(rows)} transactions replay 0 → {chain}; current stock {current}.")


def part_a() -> None:
    lines.append("## Part A: real app, MySQL test database, stand-in Authentication Service\n")
    lines.append("Everything below happened inside one transaction that was rolled back afterwards. "
                 f"LOW_STOCK_THRESHOLD = {get_settings().low_stock_threshold}.\n")
    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", autoflush=False, expire_on_commit=False)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_auth_client] = lambda: httpx.Client(transport=httpx.MockTransport(stand_in_auth))
    try:
        c = TestClient(app)
        admin, customer = bearer(ADMIN), bearer(CUSTOMER)
        cat = step(c, "Admin creates a category", 201, "post", "/api/categories/", headers=admin,
                   body={"name": "Evidence Inventory"}).json()

        lines.append("## Initial stock\n")
        product = step(c, "Admin creates a product with initial_stock 10", 201, "post", "/api/products/",
                       headers=admin, body={"category_id": cat["id"], "name": "Evidence Kettle", "sku": "EV-INV-1",
                                            "price": "30.00", "initial_stock": 10}).json()
        pid = product["id"]
        inv = f"/api/inventory/{pid}"
        step(c, "Its history: one IN transaction, remarks Initial stock", 200, "get", f"{inv}/history", headers=admin)
        step(c, "PATCH cannot change stock_quantity", 422, "patch", f"/api/products/{pid}", headers=admin,
             body={"stock_quantity": 99})

        lines.append("## Current stock, stock-in, stock-out\n")
        step(c, "Current stock", 200, "get", inv, headers=admin)
        step(c, "Stock-in 5", 201, "post", f"{inv}/stock-in", headers=admin,
             body={"quantity": 5, "remarks": "Supplier delivery, invoice 4471"})
        step(c, "Stock-out 3", 201, "post", f"{inv}/stock-out", headers=admin, body={"quantity": 3, "remarks": "Order 1001"})
        step(c, "Stock-out 8: down to 4, at or below the threshold", 201, "post", f"{inv}/stock-out", headers=admin,
             body={"quantity": 8})

        lines.append("## Insufficient stock and invalid quantities\n")
        step(c, "Stock-out 5 with 4 available", 409, "post", f"{inv}/stock-out", headers=admin, body={"quantity": 5})
        step(c, "Stock is still 4", 200, "get", inv, headers=admin)
        for quantity in (0, -2, 1.5, "3"):
            step(c, f"Stock-in quantity {quantity!r}", 422, "post", f"{inv}/stock-in", headers=admin,
                 body={"quantity": quantity})
        step(c, "Stock-out quantity 0", 422, "post", f"{inv}/stock-out", headers=admin, body={"quantity": 0})
        step(c, "Quantity missing", 422, "post", f"{inv}/stock-in", headers=admin, body={"remarks": "no quantity"})
        step(c, "Malformed JSON", 400, "post", f"{inv}/stock-in", headers=admin, raw=b'{"quantity": ')

        lines.append("## Invalid and unknown product IDs\n")
        step(c, "Unknown product: stock", 404, "get", "/api/inventory/999999", headers=admin)
        step(c, "Unknown product: stock-in", 404, "post", "/api/inventory/999999/stock-in", headers=admin,
             body={"quantity": 1})
        step(c, "Unknown product: stock-out", 404, "post", "/api/inventory/999999/stock-out", headers=admin,
             body={"quantity": 1})
        step(c, "Unknown product: history", 404, "get", "/api/inventory/999999/history", headers=admin)
        step(c, "Invalid product ID 0", 422, "get", "/api/inventory/0", headers=admin)
        step(c, "Invalid product ID abc", 422, "post", "/api/inventory/abc/stock-out", headers=admin,
             body={"quantity": 1})

        lines.append("## Access\n")
        step(c, "Customer cannot stock-in", 403, "post", f"{inv}/stock-in", headers=customer, body={"quantity": 1})
        step(c, "Customer cannot stock-out", 403, "post", f"{inv}/stock-out", headers=customer, body={"quantity": 1})
        step(c, "Anonymous cannot stock-in", 401, "post", f"{inv}/stock-in", body={"quantity": 1})
        step(c, "Customer cannot read the history", 403, "get", f"{inv}/history", headers=customer)

        lines.append("## A failed write is rolled back\n")
        lines.append("A listener makes MySQL's `INSERT INTO inventory_transactions` fail, as a lost connection "
                     "would, after the product's `UPDATE` has already been sent in the same transaction.\n")

        def fail_history_insert(_conn, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith("INSERT INTO INVENTORY_TRANSACTIONS"):
                raise OperationalError("INSERT", {}, Exception("injected failure"))

        event.listen(engine, "before_cursor_execute", fail_history_insert)
        try:
            step(c, "Stock-in 50 while the history insert fails", 503, "post", f"{inv}/stock-in", headers=admin,
                 body={"quantity": 50})
        finally:
            event.remove(engine, "before_cursor_execute", fail_history_insert)
        after = step(c, "Stock afterwards: still 4, the UPDATE was rolled back", 200, "get", inv, headers=admin).json()
        check("stock unchanged", after["stock_quantity"] == 4, f"stock_quantity = {after['stock_quantity']}.")
        step(c, "The row lock was released: the next stock-in works", 201, "post", f"{inv}/stock-in", headers=admin,
             body={"quantity": 1})

        lines.append("## History and low stock\n")
        history = step(c, "Complete history, newest first", 200, "get", f"{inv}/history", headers=admin).json()
        check("history length", history["total"] == 5,
              f"total = {history['total']}: initial 10, +5, −3, −8, +1 (the failed +50 is absent).")
        step(c, "History page 2 of 3, two per page", 200, "get", f"{inv}/history", headers=admin,
             params={"page": 2, "page_size": 2})
        step(c, "Only OUT transactions", 200, "get", f"{inv}/history", headers=admin, params={"transaction_type": "OUT"})
        check_consistent(c, pid, admin)
        report = step(c, "Low-stock report", 200, "get", "/api/inventory/low-stock", headers=admin).json()
        row = next((r for r in report if r["product_id"] == pid), None)
        check("product in low-stock report", row is not None and row["stock_quantity"] == 5,
              f"stock 5 ≤ threshold {get_settings().low_stock_threshold}: {row}.")
        step(c, "Stock-in 20", 201, "post", f"{inv}/stock-in", headers=admin, body={"quantity": 20})
        report = step(c, "Low-stock report again", 200, "get", "/api/inventory/low-stock", headers=admin).json()
        check("product left the report", all(r["product_id"] != pid for r in report), "stock 25 is above the threshold.")
        check_consistent(c, pid, admin)
    finally:
        app.dependency_overrides.clear()
        session.close()
        outer.rollback()
        conn.close()
    lines.append("Transaction rolled back: the test database holds none of the rows above.\n")


def part_b() -> None:
    lines.append("## Part B: live container, real Authentication Service\n")
    lines.append(f"Base URL `{CATALOG}`. Only requests that must be refused.\n")
    with httpx.Client(base_url=CATALOG, timeout=10) as c:
        forged = bearer(token("ADMIN"))
        step(c, "Current stock without a token", 401, "get", "/api/inventory/1")
        step(c, "Stock-in without a token", 401, "post", "/api/inventory/1/stock-in", body={"quantity": 1})
        step(c, "Stock-out without a token", 401, "post", "/api/inventory/1/stock-out", body={"quantity": 1})
        step(c, "History without a token", 401, "get", "/api/inventory/1/history")
        step(c, "Low-stock report without a token", 401, "get", "/api/inventory/low-stock")
        step(c, "Stock-in with a forged ADMIN token (rejected by the real Authentication Service)", 401, "post",
             "/api/inventory/1/stock-in", headers=forged, body={"quantity": 1})


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    database = get_settings().mysql_database
    if database != TEST_DATABASE:
        print(f"Refusing to run Part A against {database!r}; set MYSQL_DATABASE={TEST_DATABASE}")
        return 2
    lines.append("# Inventory API evidence\n")
    lines.append(f"Recorded {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC by `python -m scripts.inventory_evidence`.\n")
    part_a()
    part_b()
    passed = sum(results)
    lines.insert(2, f"**{passed} of {len(results)} checks passed** (every HTTP status and every content check).\n")
    Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)
    Path(sys.argv[1]).write_text("\n".join(lines), encoding="utf-8")
    print(f"{passed} of {len(results)} checks passed; written to {sys.argv[1]}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
