"""Live check of scenario 18 with a real customer token (Task 12 follow-up).

    $env:CUSTOMER_EMAIL="..."; $env:CUSTOMER_PASSWORD="..."; python -m scripts.live_customer_check

Logs in to the real Authentication Service (port 8001) as a USER account, then calls every ADMIN
route of the running Catalog Service container (port 8006) with that token. Each must answer 403.
Public reads with the same token must answer 200, and `include_inactive=true` (ADMIN only) 403.
Nothing is created or changed: every ADMIN request is refused before it reaches the database.

The credentials come from environment variables only; the token is never written to the log.
Output: DELIVERABELS/Test_Results/live_customer/live_customer_check.txt
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "DELIVERABELS" / "Test_Results" / "live_customer" / "live_customer_check.txt"
AUTH, CATALOG = "http://127.0.0.1:8001", "http://127.0.0.1:8006"

CHECKS = [  # method, path, json body, expected status
    ("POST", "/api/categories/", {"name": "Customer attempt"}, 403),
    ("PUT", "/api/categories/1", {"name": "x", "description": None, "is_active": True}, 403),
    ("PATCH", "/api/categories/1", {"name": "x"}, 403),
    ("DELETE", "/api/categories/1", None, 403),
    ("POST", "/api/products/", {"category_id": 1, "name": "Customer attempt", "sku": "CUST-1", "price": "1.00"}, 403),
    ("PUT", "/api/products/1", {"category_id": 1, "name": "x", "sku": "X-1", "price": "1.00"}, 403),
    ("PATCH", "/api/products/1", {"price": "1.00"}, 403),
    ("DELETE", "/api/products/1", None, 403),
    ("GET", "/api/inventory/1", None, 403),
    ("POST", "/api/inventory/1/stock-in", {"quantity": 1}, 403),
    ("POST", "/api/inventory/1/stock-out", {"quantity": 1}, 403),
    ("GET", "/api/inventory/1/history", None, 403),
    ("GET", "/api/inventory/low-stock", None, 403),
    ("GET", "/api/products/?include_inactive=true", None, 403),
    ("GET", "/api/categories/?include_inactive=true", None, 403),
    ("GET", "/api/products/", None, 200),
    ("GET", "/api/categories/", None, 200),
]


def main() -> int:
    email, password = os.environ.get("CUSTOMER_EMAIL"), os.environ.get("CUSTOMER_PASSWORD")
    if not email or not password:
        print("Set CUSTOMER_EMAIL and CUSTOMER_PASSWORD (a USER account of the Authentication Service).")
        return 2
    lines = [f"Live customer check, {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC",
             f"Authentication Service {AUTH} (real), Catalog Service {CATALOG} (running container)", ""]
    login = httpx.post(f"{AUTH}/api/auth/login", json={"email": email, "password": password}, timeout=10)
    body = login.json()
    token = body.get("access_token")
    role = (body.get("user") or {}).get("role")
    lines.append(f"Login as the customer account: HTTP {login.status_code}, token received: {bool(token)}, "
                 f"role in the login answer: {role}")
    if not token:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text("\n".join(lines) + "\nFAIL: no token\n", encoding="utf-8")
        return 1
    headers = {"Authorization": f"Bearer {token}"}
    passed = failed = 0
    lines.append("")
    for method, path, payload, expected in CHECKS:
        r = httpx.request(method, CATALOG + path, json=payload, headers=headers, timeout=10)
        ok = r.status_code == expected
        passed, failed = passed + ok, failed + (not ok)
        detail = r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") \
            and isinstance(r.json(), dict) else ""
        lines.append(f"{'PASS' if ok else 'FAIL'}  {method:6} {path:42} expected {expected}, got {r.status_code}"
                     + (f"  detail: {detail}" if detail else ""))
    lines += ["", f"{passed} passed, {failed} failed. The token is not recorded."]
    text = "\n".join(lines) + "\n"
    assert token not in text
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
