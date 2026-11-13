"""Record evidence for search, filters, paging and sorting on GET /api/products/.

    $env:MYSQL_DATABASE = "shopease_product_catalog_test_db"
    python -m scripts.product_search_evidence DELIVERABELS/Test_Results/product_search_logs/02_search_transcript.md

Part A: the real application in-process, against the real MySQL test database, inside one
transaction that is rolled back at the end. A known catalogue is created first, so every listing
can be checked against the exact SKUs expected, in order, not only the status. The SQL sent to
MySQL for one combined request is recorded too. Only the Authentication Service is a stand-in
(the live one has no ADMIN account). Refuses any database but the test one.

Part B: the running Catalog Service container with its configured database and the real
Authentication Service. Read-only: the example requests from the task, as an anonymous visitor,
checked for consistent paging data, plus requests that must be refused.

Uses the step recorder of scripts.product_api_evidence; the transcript marks each check PASS or FAIL.
"""

import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import event
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
)

# name, sku, price, initial stock, category, hidden by
CATALOGUE = [
    ("Galaxy Mobile", "EV-MOB-100", "1500.00", 5, "phones", None),
    ("Pixel Mobile", "EV-MOB-200", "4500.00", 0, "phones", None),
    ("Budget Phone", "EV-PHN-300", "800.00", 12, "phones", None),
    ("Laptop Stand", "EV-MOBILE-STAND", "1000.00", 0, "laptops", None),
    ("Ultrabook", "EV-LAP-500", "5000.00", 7, "laptops", None),
    ("Gaming Laptop", "EV-LAP-600", "5000.01", 2, "laptops", None),
    ("Retired Mobile", "EV-MOB-900", "2000.00", 4, "phones", "product inactive"),
    ("Archive Mobile", "EV-MOB-950", "3000.00", 6, "archive", "category inactive"),
]


def check(title: str, ok: bool, detail: str) -> None:
    results.append(ok)
    lines.append(f"Check, {title}: **{'PASS' if ok else 'FAIL'}**. {detail}\n")


def listing(c, title: str, params: dict, expected_skus: list[str], *, headers=None, total=None) -> None:
    """A 200 listing whose SKUs (in order) and total must be exactly as expected."""
    response = step(c, title, 200, "get", "/api/products/", headers=headers, params=params)
    body = response.json()
    got = [p["sku"] for p in body.get("items", [])]
    expected_total = len(expected_skus) if total is None else total
    check("SKUs in order", got == expected_skus, f"Expected `{expected_skus}`, got `{got}`.")
    check("total", body.get("total") == expected_total, f"Expected {expected_total}, got {body.get('total')}.")


def build_catalogue(c, admin) -> dict:
    lines.append("## Setup: a known catalogue\n")
    lines.append("| Name | SKU | Price | Stock | Category | Hidden from customers because |\n|---|---|---|---|---|---|")
    for name, sku, price, stock, category, hidden_by in CATALOGUE:
        lines.append(f"| {name} | {sku} | {price} | {stock} | {category} | {hidden_by or ''} |")
    lines.append("")
    categories = {}
    for key in ("phones", "laptops", "archive"):
        categories[key] = step(c, f"Admin creates category Evidence {key.title()}", 201, "post",
                               "/api/categories/", headers=admin, body={"name": f"Evidence {key.title()}"}).json()
    retired = None
    created = []
    for name, sku, price, stock, category, hidden_by in CATALOGUE:
        response = c.post("/api/products/", headers=admin, json={
            "name": name, "sku": sku, "price": price, "initial_stock": stock,
            "category_id": categories[category]["id"]})
        created.append(response.status_code == 201)
        if hidden_by == "product inactive":
            retired = response.json()
    check("eight products created", all(created),
          "Created with `POST /api/products/`; each must answer 201 (responses not repeated).")
    step(c, "Admin deactivates Retired Mobile", 200, "patch", f"/api/products/{retired['id']}", headers=admin,
         body={"is_active": False})
    step(c, "Admin deactivates category Evidence Archive", 200, "patch",
         f"/api/categories/{categories['archive']['id']}", headers=admin, body={"is_active": False})
    return categories


def part_a() -> None:
    lines.append("## Part A: real app, MySQL test database, stand-in Authentication Service\n")
    lines.append("Everything below happened inside one transaction that was rolled back afterwards. "
                 "`search=EV-` limits each listing to the evidence products, in case the test database "
                 "holds other rows.\n")
    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", autoflush=False, expire_on_commit=False)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_auth_client] = lambda: httpx.Client(transport=httpx.MockTransport(stand_in_auth))
    try:
        c = TestClient(app)
        admin, customer = bearer(ADMIN), bearer(CUSTOMER)
        cats = build_catalogue(c, admin)
        phones, laptops, archive = (cats[k]["id"] for k in ("phones", "laptops", "archive"))
        ev = {"search": "EV-"}

        lines.append("## The task's example requests (as a customer)\n")
        listing(c, "search=mobile (name or SKU; hidden products left out)", {"search": "mobile"},
                ["EV-MOB-100", "EV-MOBILE-STAND", "EV-MOB-200"], headers=customer)
        listing(c, "category_id", {"category_id": phones}, ["EV-PHN-300", "EV-MOB-100", "EV-MOB-200"],
                headers=customer)
        listing(c, "min_price=1000&max_price=5000 (inclusive)", ev | {"min_price": "1000", "max_price": "5000"},
                ["EV-MOB-100", "EV-MOBILE-STAND", "EV-MOB-200", "EV-LAP-500"], headers=customer)
        listing(c, "page=1&page_size=10", ev | {"page": 1, "page_size": 10},
                ["EV-PHN-300", "EV-MOB-100", "EV-LAP-600", "EV-MOBILE-STAND", "EV-MOB-200", "EV-LAP-500"],
                headers=customer)
        listing(c, "sort_by=price&sort_order=asc", ev | {"sort_by": "price", "sort_order": "asc"},
                ["EV-PHN-300", "EV-MOBILE-STAND", "EV-MOB-100", "EV-MOB-200", "EV-LAP-500", "EV-LAP-600"],
                headers=customer)

        lines.append("## Filters and combinations\n")
        listing(c, "availability=in_stock", ev | {"availability": "in_stock"},
                ["EV-PHN-300", "EV-MOB-100", "EV-LAP-600", "EV-LAP-500"], headers=customer)
        listing(c, "availability=out_of_stock", ev | {"availability": "out_of_stock"},
                ["EV-MOBILE-STAND", "EV-MOB-200"], headers=customer)
        listing(c, "search + category + price range + availability + sort",
                {"search": "mobile", "category_id": phones, "min_price": "1000", "max_price": "5000",
                 "availability": "in_stock", "sort_by": "price", "sort_order": "desc"},
                ["EV-MOB-100"], headers=customer)
        listing(c, "category + availability, newest first", {"category_id": laptops, "availability": "in_stock",
                                                              "sort_by": "created_at", "sort_order": "desc"},
                ["EV-LAP-600", "EV-LAP-500"], headers=customer)
        listing(c, "Nothing matches", {"search": "EV-ZZZ"}, [], headers=customer)

        lines.append("## Pagination\n")
        listing(c, "Page 1 of 3, two per page, by price", ev | {"page": 1, "page_size": 2, "sort_by": "price"},
                ["EV-PHN-300", "EV-MOBILE-STAND"], headers=customer, total=6)
        listing(c, "Page 3 of 3", ev | {"page": 3, "page_size": 2, "sort_by": "price"},
                ["EV-LAP-500", "EV-LAP-600"], headers=customer, total=6)
        last = c.get("/api/products/", headers=customer, params=ev | {"page": 3, "page_size": 2}).json()
        check("paging fields", (last["page"], last["page_size"], last["total_pages"]) == (3, 2, 3),
              f"page={last['page']}, page_size={last['page_size']}, total_pages={last['total_pages']}.")
        listing(c, "Page past the end: empty, total still correct", ev | {"page": 9, "page_size": 2}, [],
                headers=customer, total=6)

        lines.append("## Visibility\n")
        listing(c, "Customer searches for the inactive product's exact SKU", {"search": "EV-MOB-900"}, [],
                headers=customer)
        listing(c, "Customer filters on the inactive category", {"category_id": archive}, [], headers=customer)
        listing(c, "Anonymous visitor, same search as above", {"search": "mobile"},
                ["EV-MOB-100", "EV-MOBILE-STAND", "EV-MOB-200"])
        listing(c, "Admin with include_inactive also sees both hidden products", {"search": "mobile", "include_inactive": "true"},
                ["EV-MOB-950", "EV-MOB-100", "EV-MOBILE-STAND", "EV-MOB-200", "EV-MOB-900"], headers=admin)
        step(c, "Customer asks for include_inactive", 403, "get", "/api/products/", headers=customer,
             params={"include_inactive": "true"})

        lines.append("## Database-level filtering and paging\n")
        statements: list[str] = []

        def record(_conn, _cursor, statement, parameters, _context, _many):
            if "FROM products" in statement:
                statements.append(f"{' '.join(statement.split())}\n-- parameters: {parameters}")

        event.listen(engine, "before_cursor_execute", record)
        try:
            listing(c, "Combined request whose SQL is shown below",
                    {"search": "mobile", "min_price": "1000", "availability": "in_stock", "page": 1,
                     "page_size": 2, "sort_by": "price", "sort_order": "desc"},
                    ["EV-MOB-100"], headers=customer)
        finally:
            event.remove(engine, "before_cursor_execute", record)
        check("two queries: COUNT, then one page with LIMIT", len(statements) == 2
              and "count(" in statements[0].lower() and "LIMIT" in statements[1],
              f"{len(statements)} statements sent for the products table.")
        lines.append("SQL sent to MySQL for that request:\n```sql\n" + "\n\n".join(statements) + "\n```\n")
    finally:
        app.dependency_overrides.clear()
        session.close()
        outer.rollback()
        conn.close()
    lines.append("Transaction rolled back: the test database holds none of the rows above.\n")


def part_b() -> None:
    lines.append("## Part B: live container, configured database, real Authentication Service\n")
    lines.append(f"Base URL `{CATALOG}`. Read-only, as an anonymous visitor. The result depends on what the "
                 "configured database holds, so the checks are on consistency: paging fields, page size, and "
                 "that every product returned is active and matches the filter.\n")
    with httpx.Client(base_url=CATALOG, timeout=10) as c:
        for title, params, rule in [
            ("search=mobile", {"search": "mobile"},
             lambda p: "mobile" in p["name"].lower() or "mobile" in p["sku"].lower()),
            ("category_id=1", {"category_id": 1}, lambda p: p["category_id"] == 1),
            ("min_price=1000&max_price=5000", {"min_price": "1000", "max_price": "5000"},
             lambda p: 1000 <= float(p["price"]) <= 5000),
            ("page=1&page_size=10", {"page": 1, "page_size": 10}, lambda p: True),
            ("sort_by=price&sort_order=asc", {"sort_by": "price", "sort_order": "asc"}, lambda p: True),
            ("availability=out_of_stock", {"availability": "out_of_stock"}, lambda p: p["stock_quantity"] == 0),
        ]:
            body = step(c, title, 200, "get", "/api/products/", params=params).json()
            items = body["items"]
            size = params.get("page_size", 20)
            consistent = (body["page_size"] == size and len(items) <= size
                          and body["total_pages"] == math.ceil(body["total"] / size)
                          and all(p["is_active"] for p in items) and all(rule(p) for p in items))
            check("consistent", consistent, f"{len(items)} items, total {body['total']}, "
                                            f"total_pages {body['total_pages']}.")
            if params.get("sort_by") == "price":
                prices = [float(p["price"]) for p in items]
                check("ascending prices", prices == sorted(prices), f"`{prices}`")
        step(c, "page=0", 422, "get", "/api/products/", params={"page": 0})
        step(c, "page=-1", 422, "get", "/api/products/", params={"page": -1})
        step(c, "page_size=101", 422, "get", "/api/products/", params={"page_size": 101})
        step(c, "sort_by not allowed", 422, "get", "/api/products/", params={"sort_by": "id; DROP TABLE products"})
        step(c, "sort_order not allowed", 422, "get", "/api/products/", params={"sort_order": "up"})
        step(c, "availability not allowed", 422, "get", "/api/products/", params={"availability": "maybe"})
        step(c, "max_price below min_price", 422, "get", "/api/products/", params={"min_price": 50, "max_price": 10})
        step(c, "Unknown parameter", 422, "get", "/api/products/", params={"size": 10})
        step(c, "include_inactive without a token", 401, "get", "/api/products/", params={"include_inactive": "true"})


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    database = get_settings().mysql_database
    if database != TEST_DATABASE:
        print(f"Refusing to run Part A against {database!r}; set MYSQL_DATABASE={TEST_DATABASE}")
        return 2
    lines.append("# Product search, filtering, pagination and sorting: evidence\n")
    lines.append(f"Recorded {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC by "
                 "`python -m scripts.product_search_evidence`.\n")
    part_a()
    part_b()
    passed = sum(results)
    lines.insert(2, f"**{passed} of {len(results)} checks passed** (every HTTP status and every listing check).\n")
    Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)
    Path(sys.argv[1]).write_text("\n".join(lines), encoding="utf-8")
    print(f"{passed} of {len(results)} checks passed; written to {sys.argv[1]}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
