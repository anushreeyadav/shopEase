"""In-memory stand-ins for product_service, user_service and auth_service (httpx.MockTransport).

They follow the real contracts (rest_api_notes.md Part 4) closely enough to exercise every
checkout branch, and can inject failures per operation: "timeout", "connect", an HTTP status,
or "apply_then_timeout" (the call takes effect but the response is lost).
"""

import json
import sqlite3
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx

SERVICE_TOKEN = "fake-service-token"


class FakeDependencies:
    def __init__(self, db_path: str | None = None) -> None:
        self.products: dict[str, dict] = {}
        self.reservations: dict[str, dict] = {}
        self.addresses: dict[tuple[str, str], dict] = {}
        self.failures: dict[str, deque] = defaultdict(deque)
        self.calls: list[tuple[str, httpx.Request]] = []
        self.db_path = db_path  # when set, assert no write transaction is open during calls
        self.lock_violations: list[str] = []

    # --- setup helpers ---------------------------------------------------------------------

    def add_product(self, name: str, price: str, stock: int, status: str = "ACTIVE", currency: str = "INR") -> str:
        pid = str(uuid.uuid4())
        self.products[pid] = {"name": name, "price": price, "stock": stock, "reserved": 0,
                              "status": status, "currency": currency}
        return pid

    def add_address(self, user_id, **overrides) -> str:
        address_id = str(uuid.uuid4())
        self.addresses[(str(user_id), address_id)] = {
            "address_id": address_id, "label": "Home", "line1": "12 Example Street", "line2": "Flat 4B",
            "city": "Pune", "state": "Maharashtra", "postal_code": "411001", "country": "IN",
            "is_default": True, **overrides,
        }
        return address_id

    def fail(self, operation: str, *actions) -> None:
        self.failures[operation].extend(actions)

    def count(self, operation: str) -> int:
        return sum(1 for op, _ in self.calls if op == operation)

    def available(self, pid: str) -> int:
        p = self.products[pid]
        return p["stock"] - p["reserved"]

    def expire_reservation(self, order_id) -> None:
        self.reservations[str(order_id)]["expires_at"] = datetime.now(UTC) - timedelta(minutes=1)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    # --- request handling ----------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        operation = self._operation(request.method, path)
        self.calls.append((operation, request))
        self._check_no_open_write_transaction(operation)
        if operation != "token" and request.headers.get("Authorization") != f"Bearer {SERVICE_TOKEN}":
            return httpx.Response(401, json={"error": {"code": "INVALID_TOKEN"}})

        action = self.failures[operation].popleft() if self.failures[operation] else None
        if action == "timeout":
            raise httpx.ReadTimeout("simulated", request=request)
        if action == "connect":
            raise httpx.ConnectError("simulated", request=request)
        if isinstance(action, int):
            return httpx.Response(action, json={"error": {"code": "SIMULATED"}})

        response = getattr(self, f"_{operation}")(request, path)
        if action == "apply_then_timeout":
            raise httpx.ReadTimeout("simulated after applying", request=request)
        return response

    @staticmethod
    def _operation(method: str, path: str) -> str:
        if path.endswith("/service-token"):
            return "token"
        if path.endswith("/price-check"):
            return "price_check"
        if path == "/internal/reservations":
            return "reserve"
        if path.endswith("/confirm"):
            return "confirm"
        if path.endswith("/release"):
            return "release"
        if "/addresses/" in path:
            return "address"
        raise AssertionError(f"unexpected call {method} {path}")

    def _check_no_open_write_transaction(self, operation: str) -> None:
        if not self.db_path:
            return
        probe = sqlite3.connect(self.db_path, timeout=0)
        try:
            probe.execute("BEGIN IMMEDIATE")
            probe.execute("ROLLBACK")
        except sqlite3.OperationalError:
            self.lock_violations.append(operation)
        finally:
            probe.close()

    def _token(self, request, path):
        body = json.loads(request.content)
        if body["client_id"] != "svc:order" or not body["client_secret"]:
            return httpx.Response(401, json={"error": {"code": "INVALID_CLIENT"}})
        return httpx.Response(200, json={"access_token": SERVICE_TOKEN, "token_type": "Bearer", "expires_in": 300,
                                         "scope": "products:read inventory:reserve addresses:read"})

    def _price_check(self, request, path):
        ids = json.loads(request.content)["product_ids"]
        items = [
            {"product_id": pid, "sku": "SKU", "name": p["name"], "price": p["price"], "currency": p["currency"],
             "status": p["status"], "available_quantity": p["stock"] - p["reserved"],
             "orderable": p["status"] == "ACTIVE" and p["stock"] > p["reserved"]}
            for pid in ids if (p := self.products.get(pid))
        ]
        return httpx.Response(200, json={"items": items, "missing": [pid for pid in ids if pid not in self.products]})

    def _reservation_body(self, order_id: str, status_code: int):
        r = self.reservations[order_id]
        return httpx.Response(status_code, json={
            "order_id": order_id, "status": r["status"],
            "expires_at": r["expires_at"].isoformat().replace("+00:00", "Z"),
            "items": [{"product_id": pid, "quantity": q, "status": r["status"]} for pid, q in r["items"].items()],
        })

    def _reserve(self, request, path):
        body = json.loads(request.content)
        order_id = body["order_id"]
        items = {i["product_id"]: i["quantity"] for i in body["items"]}
        if order_id in self.reservations:
            if self.reservations[order_id]["items"] != items:
                return httpx.Response(409, json={"error": {"code": "RESERVATION_CONFLICT"}})
            return self._reservation_body(order_id, 200)
        short = [pid for pid, q in items.items() if self.available(pid) < q]
        if short:
            return httpx.Response(409, json={"error": {
                "code": "OUT_OF_STOCK", "message": "Not enough stock for some items; nothing was reserved.",
                "details": [{"field": "body.items", "issue": f"product {pid}"} for pid in short]}})
        for pid, q in items.items():
            self.products[pid]["reserved"] += q
        self.reservations[order_id] = {"items": items, "status": "RESERVED",
                                       "expires_at": datetime.now(UTC) + timedelta(minutes=15)}
        return self._reservation_body(order_id, 201)

    def _confirm(self, request, path):
        order_id = path.split("/")[3]
        r = self.reservations.get(order_id)
        if r is None:
            return httpx.Response(404, json={"error": {"code": "RESERVATION_NOT_FOUND"}})
        if r["status"] == "CONFIRMED":
            return self._reservation_body(order_id, 200)
        if r["status"] != "RESERVED" or r["expires_at"] <= datetime.now(UTC):
            if r["status"] == "RESERVED":
                self._return_stock(r, "EXPIRED")
            return httpx.Response(409, json={"error": {"code": "RESERVATION_EXPIRED"}})
        for pid, q in r["items"].items():
            self.products[pid]["stock"] -= q
            self.products[pid]["reserved"] -= q
        r["status"] = "CONFIRMED"
        return self._reservation_body(order_id, 200)

    def _release(self, request, path):
        order_id = path.split("/")[3]
        r = self.reservations.get(order_id)
        if r is None:
            return httpx.Response(200, json={"order_id": order_id, "released_items": 0})
        if r["status"] == "CONFIRMED":
            return httpx.Response(409, json={"error": {"code": "RESERVATION_ALREADY_CONFIRMED"}})
        released = len(r["items"]) if r["status"] == "RESERVED" else 0
        if r["status"] == "RESERVED":
            self._return_stock(r, "RELEASED")
        return httpx.Response(200, json={"order_id": order_id, "released_items": released})

    def _return_stock(self, reservation: dict, status: str) -> None:
        for pid, q in reservation["items"].items():
            self.products[pid]["reserved"] -= q
        reservation["status"] = status

    def _address(self, request, path):
        if not request.headers.get("X-User-Token"):
            return httpx.Response(401, json={"error": {"code": "UNAUTHENTICATED"}})
        parts = path.split("/")
        address = self.addresses.get((parts[3], parts[5]))
        if address is None:
            return httpx.Response(404, json={"error": {"code": "ADDRESS_NOT_FOUND"}})
        return httpx.Response(200, json={**address, "created_at": "2026-10-30T10:00:00Z",
                                         "updated_at": "2026-10-30T10:00:00Z"})


def money(value) -> Decimal:
    return Decimal(str(value))
