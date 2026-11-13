"""Record request/response evidence for the product API.

    $env:MYSQL_DATABASE = "shopease_product_catalog_test_db"
    python -m scripts.product_api_evidence DELIVERABELS/Test_Results/product_api_logs/02_api_transcript.md

Part A: the real application in-process, against the real MySQL test database, inside one
transaction that is rolled back at the end (nothing is kept). Only the Authentication Service is
replaced by a stand-in, because the live one has no ADMIN account: tokens marked ADMIN or USER are
answered the way its POST /api/auth/verify-token answers. Refuses any database but the test one.

Part B: the running Catalog Service container (CATALOG_BASE_URL, default http://127.0.0.1:8006)
with its configured database and the real Authentication Service. Only reads and requests that
must be refused are sent, so nothing is changed.

Every step has an expected status; the transcript marks each PASS or FAIL.
"""

import json
import os
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import get_auth_client
from app.database.connection import engine, get_db
from app.main import app

TEST_DATABASE = "shopease_product_catalog_test_db"
CATALOG = os.environ.get("CATALOG_BASE_URL", "http://127.0.0.1:8006").rstrip("/")
lines: list[str] = []
results: list[bool] = []


def token(role: str) -> str:
    """A well-formed HS256 token (random key). Only the stand-in decides what it means."""
    now = int(time.time())
    return jwt.encode({"sub": "1" if role == "ADMIN" else "2", "role": role, "iat": now, "exp": now + 600},
                      secrets.token_urlsafe(32), algorithm="HS256")


ADMIN, CUSTOMER = token("ADMIN"), token("USER")
USERS = {ADMIN: (1, "ADMIN"), CUSTOMER: (2, "USER")}


def stand_in_auth(request: httpx.Request) -> httpx.Response:
    presented = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if presented not in USERS:
        return httpx.Response(401, json={"detail": "Could not validate credentials"})
    user_id, role = USERS[presented]
    return httpx.Response(200, json={"valid": True, "user": {
        "id": user_id, "full_name": f"Evidence {role}", "email": f"{role.lower()}@example.com",
        "role": role, "is_active": True}})


def caller_name(headers: dict) -> str:
    value = headers.get("Authorization", "")
    if not value:
        return "anonymous"
    presented = value.removeprefix("Bearer ")
    return {ADMIN: "ADMIN", CUSTOMER: "CUSTOMER (USER)"}.get(presented, "forged token")


def step(client, title: str, expected: int, method: str, path: str, *, headers=None, body=None, raw=None,
         params=None) -> httpx.Response:
    headers = headers or {}
    kwargs = {"headers": dict(headers), "params": params}
    if raw is not None:
        kwargs["content"] = raw
        kwargs["headers"]["Content-Type"] = "application/json"
    elif body is not None:
        kwargs["json"] = body
    response = client.request(method, path, **kwargs)
    ok = response.status_code == expected
    results.append(ok)
    query = ("?" + "&".join(f"{k}={v}" for k, v in params.items())) if params else ""
    lines.append(f"### {'PASS' if ok else 'FAIL'}: {title}\n")
    lines.append(f"`{method.upper()} {path}{query}` as **{caller_name(headers)}**, "
                 f"expected **{expected}**, got **{response.status_code}**\n")
    if raw is not None:
        lines.append(f"Request body (raw): `{raw.decode()}`\n")
    elif body is not None:
        lines.append("Request body:\n```json\n" + json.dumps(body, indent=2) + "\n```\n")
    try:
        shown = json.dumps(response.json(), indent=2)
    except ValueError:
        shown = response.text
    lines.append("Response:\n```json\n" + shown + "\n```\n")
    return response


def bearer(value: str) -> dict:
    return {"Authorization": f"Bearer {value}"}


def part_a() -> None:
    lines.append("## Part A: write scenarios (real app, MySQL test database, stand-in Authentication Service)\n")
    lines.append("All changes below were made inside one transaction that was rolled back afterwards.\n")
    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", autoflush=False, expire_on_commit=False)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_auth_client] = lambda: httpx.Client(transport=httpx.MockTransport(stand_in_auth))
    try:
        c = TestClient(app)
        admin, customer = bearer(ADMIN), bearer(CUSTOMER)
        cat = step(c, "Admin creates a category", 201, "post", "/api/categories/", headers=admin,
                   body={"name": "Evidence Apparel"}).json()
        closed = step(c, "Admin creates a second category, to be deactivated", 201, "post", "/api/categories/",
                      headers=admin, body={"name": "Evidence Archive"}).json()
        step(c, "Admin deactivates it", 200, "patch", f"/api/categories/{closed['id']}", headers=admin,
             body={"is_active": False})

        lines.append("## Create\n")
        tee = step(c, "Admin creates a product with initial stock", 201, "post", "/api/products/", headers=admin,
                   body={"category_id": cat["id"], "name": "Red  Cotton T-Shirt", "sku": "ev-tee-red-m",
                         "price": "19.5", "discount_price": "14.99", "brand": "Basics",
                         "image_url": "https://cdn.example.com/tee.png", "initial_stock": 25}).json()
        step(c, "Duplicate SKU, different letter case", 409, "post", "/api/products/", headers=admin,
             body={"category_id": cat["id"], "name": "Copy", "sku": "EV-TEE-RED-M", "price": "5.00"})
        step(c, "Required fields missing", 422, "post", "/api/products/", headers=admin, body={})
        step(c, "Negative price", 422, "post", "/api/products/", headers=admin,
             body={"category_id": cat["id"], "name": "Bad", "sku": "EV-BAD-1", "price": "-1.00"})
        step(c, "Discount equal to price", 422, "post", "/api/products/", headers=admin,
             body={"category_id": cat["id"], "name": "Bad", "sku": "EV-BAD-2", "price": "10.00",
                   "discount_price": "10.00"})
        step(c, "Three decimal places", 422, "post", "/api/products/", headers=admin,
             body={"category_id": cat["id"], "name": "Bad", "sku": "EV-BAD-3", "price": "1.999"})
        step(c, "Negative initial stock", 422, "post", "/api/products/", headers=admin,
             body={"category_id": cat["id"], "name": "Bad", "sku": "EV-BAD-4", "price": "1.00", "initial_stock": -3})
        step(c, "stock_quantity cannot be set", 422, "post", "/api/products/", headers=admin,
             body={"category_id": cat["id"], "name": "Bad", "sku": "EV-BAD-5", "price": "1.00", "stock_quantity": 5})
        step(c, "Category does not exist", 422, "post", "/api/products/", headers=admin,
             body={"category_id": 999999, "name": "Bad", "sku": "EV-BAD-6", "price": "1.00"})
        step(c, "Category is inactive", 422, "post", "/api/products/", headers=admin,
             body={"category_id": closed["id"], "name": "Bad", "sku": "EV-BAD-7", "price": "1.00"})
        step(c, "Malformed JSON", 400, "post", "/api/products/", headers=admin, raw=b'{"name": "x",')
        step(c, "Customer cannot create", 403, "post", "/api/products/", headers=customer,
             body={"category_id": cat["id"], "name": "Nope", "sku": "EV-NOPE", "price": "1.00"})
        step(c, "Anonymous cannot create", 401, "post", "/api/products/",
             body={"category_id": cat["id"], "name": "Nope", "sku": "EV-NOPE", "price": "1.00"})

        lines.append("## Read\n")
        mug = step(c, "Admin creates a second product", 201, "post", "/api/products/", headers=admin,
                   body={"category_id": cat["id"], "name": "Plain Mug", "sku": "EV-MUG", "price": "8.00"}).json()
        step(c, "Customer lists products", 200, "get", "/api/products/", headers=customer)
        step(c, "Customer gets a product", 200, "get", f"/api/products/{tee['id']}", headers=customer)
        step(c, "Missing product", 404, "get", "/api/products/999999", headers=customer)
        step(c, "Invalid product ID", 422, "get", "/api/products/abc", headers=customer)
        step(c, "Customer asks for inactive products", 403, "get", "/api/products/", headers=customer,
             params={"include_inactive": "true"})

        lines.append("## Update\n")
        put_body = {"category_id": cat["id"], "name": "Red Cotton T-Shirt", "description": "Regular fit",
                    "sku": "EV-TEE-RED-M", "price": "21.00", "discount_price": None, "image_url": None,
                    "brand": "Basics", "is_active": True}
        step(c, "Admin replaces a product (PUT)", 200, "put", f"/api/products/{tee['id']}", headers=admin,
             body=put_body)
        step(c, "PUT without every field", 422, "put", f"/api/products/{tee['id']}", headers=admin,
             body={"name": "Only a name"})
        step(c, "PUT to the other product's SKU", 409, "put", f"/api/products/{mug['id']}", headers=admin,
             body=put_body | {"name": "Mug"})
        step(c, "Admin changes one field (PATCH)", 200, "patch", f"/api/products/{tee['id']}", headers=admin,
             body={"discount_price": "18.00"})
        step(c, "PATCH a discount above the stored price", 422, "patch", f"/api/products/{tee['id']}", headers=admin,
             body={"discount_price": "25.00"})
        step(c, "PATCH stock directly", 422, "patch", f"/api/products/{tee['id']}", headers=admin,
             body={"stock_quantity": -1})
        step(c, "PATCH into an inactive category", 422, "patch", f"/api/products/{tee['id']}", headers=admin,
             body={"category_id": closed["id"]})
        step(c, "PATCH a missing product", 404, "patch", "/api/products/999999", headers=admin, body={"name": "X"})
        step(c, "Customer cannot PUT", 403, "put", f"/api/products/{tee['id']}", headers=customer, body=put_body)
        step(c, "Customer cannot PATCH", 403, "patch", f"/api/products/{tee['id']}", headers=customer,
             body={"price": "0.01"})

        lines.append("## Deactivate and reactivate\n")
        step(c, "Admin deletes (deactivates) a product", 200, "delete", f"/api/products/{mug['id']}", headers=admin)
        step(c, "Customer no longer sees it", 404, "get", f"/api/products/{mug['id']}", headers=customer)
        step(c, "Customer listing leaves it out", 200, "get", "/api/products/", headers=customer)
        step(c, "Admin still sees it with include_inactive", 200, "get", f"/api/products/{mug['id']}",
             headers=admin, params={"include_inactive": "true"})
        step(c, "Admin reactivates it", 200, "patch", f"/api/products/{mug['id']}", headers=admin,
             body={"is_active": True})
        step(c, "Customer cannot delete", 403, "delete", f"/api/products/{tee['id']}", headers=customer)
        step(c, "Delete a missing product", 404, "delete", "/api/products/999999", headers=admin)

        lines.append("## Products in an inactive category\n")
        step(c, "Admin deactivates the product's category", 200, "patch", f"/api/categories/{cat['id']}",
             headers=admin, body={"is_active": False})
        step(c, "Customer listing is now empty", 200, "get", "/api/products/", headers=customer)
        step(c, "Customer gets 404 for the product", 404, "get", f"/api/products/{tee['id']}", headers=customer)
    finally:
        app.dependency_overrides.clear()
        session.close()
        outer.rollback()
        conn.close()
    lines.append("Transaction rolled back: the test database holds none of the rows above.\n")


def part_b() -> None:
    lines.append("## Part B: live container, configured database, real Authentication Service\n")
    lines.append(f"Base URL `{CATALOG}`. Only reads and refused writes.\n")
    with httpx.Client(base_url=CATALOG, timeout=10) as c:
        forged = bearer(token("ADMIN"))
        step(c, "List products, anonymous", 200, "get", "/api/products/")
        step(c, "List products without the slash, no redirect", 200, "get", "/api/products")
        step(c, "Missing product", 404, "get", "/api/products/999999")
        step(c, "Invalid product ID", 422, "get", "/api/products/0")
        step(c, "Bad query parameter", 422, "get", "/api/products/", params={"page_size": "1000"})
        step(c, "Create without a token", 401, "post", "/api/products/",
             body={"category_id": 1, "name": "X", "sku": "LIVE-X", "price": "1.00"})
        step(c, "Create with a forged ADMIN token (rejected by the real Authentication Service)", 401, "post",
             "/api/products/", headers=forged, body={"category_id": 1, "name": "X", "sku": "LIVE-X", "price": "1.00"})
        step(c, "PUT without a token", 401, "put", "/api/products/1",
             body={"category_id": 1, "name": "X", "description": None, "sku": "LIVE-X", "price": "1.00",
                   "discount_price": None, "image_url": None, "brand": None, "is_active": True})
        step(c, "PATCH without a token", 401, "patch", "/api/products/1", body={"price": "0.01"})
        step(c, "DELETE without a token", 401, "delete", "/api/products/1")
        step(c, "include_inactive without a token", 401, "get", "/api/products/", params={"include_inactive": "true"})
        step(c, "Malformed JSON", 400, "post", "/api/products/", raw=b"{not json")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    database = get_settings().mysql_database
    if database != TEST_DATABASE:
        print(f"Refusing to run Part A against {database!r}; set MYSQL_DATABASE={TEST_DATABASE}")
        return 2
    lines.append("# Product API evidence\n")
    lines.append(f"Recorded {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC by "
                 "`python -m scripts.product_api_evidence`.\n")
    part_a()
    part_b()
    passed = sum(results)
    lines.insert(2, f"**{passed} of {len(results)} steps returned the expected status.**\n")
    Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)
    Path(sys.argv[1]).write_text("\n".join(lines), encoding="utf-8")
    print(f"{passed} of {len(results)} steps as expected; written to {sys.argv[1]}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
