"""In-memory order_service and auth_service stand-ins for payment tests (httpx.MockTransport)."""

import json
import uuid
from collections import defaultdict, deque

import httpx

SERVICE_TOKEN = "fake-payment-service-token"


class FakeOrders:
    def __init__(self) -> None:
        self.orders: dict[str, dict] = {}
        self.reports: list[dict] = []
        self.failures: dict[str, deque] = defaultdict(deque)
        self.calls: list[tuple[str, httpx.Request]] = []
        # Called with the order ID just before a payment-result is applied (to simulate races).
        self.before_result = None

    def add_order(self, user_id, amount: str = "4998.00", currency: str = "INR") -> str:
        order_id = str(uuid.uuid4())
        self.orders[order_id] = {"user_id": str(user_id), "amount": amount, "currency": currency,
                                 "status": "AWAITING_PAYMENT", "payment_id": None, "payment_status": "NONE"}
        return order_id

    def fail(self, operation: str, *actions) -> None:
        self.failures[operation].extend(actions)

    def outcomes(self, order_id) -> list[str]:
        return [r["outcome"] for r in self.reports if r["order_id"] == str(order_id)]

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        op = "token" if path.endswith("/service-token") else "payable" if path.endswith("/payable") else "result"
        self.calls.append((op, request))
        if op != "token" and request.headers.get("Authorization") != f"Bearer {SERVICE_TOKEN}":
            return httpx.Response(401, json={"error": {"code": "INVALID_TOKEN"}})
        action = self.failures[op].popleft() if self.failures[op] else None
        if action == "timeout":
            raise httpx.ReadTimeout("simulated", request=request)
        if action == "connect":
            raise httpx.ConnectError("simulated", request=request)
        if isinstance(action, int):
            return httpx.Response(action, json={"error": {"code": "SIMULATED"}})

        if op == "token":
            body = json.loads(request.content)
            ok = body["client_id"] == "svc:payment" and body["client_secret"]
            return httpx.Response(200 if ok else 401, json={"access_token": SERVICE_TOKEN, "expires_in": 300,
                                                            "token_type": "Bearer"})
        order_id = path.split("/")[3]
        order = self.orders.get(order_id)
        if order is None:
            return httpx.Response(404, json={"error": {"code": "ORDER_NOT_FOUND"}})
        if op == "payable":
            return httpx.Response(200, json={
                "order_id": order_id, "user_id": order["user_id"], "status": order["status"],
                "payment_status": order["payment_status"], "payable": order["status"] == "AWAITING_PAYMENT",
                "amount": order["amount"], "currency": order["currency"], "payment_due_by": None})

        if self.before_result is not None:
            self.before_result(order_id)
        report = {**json.loads(request.content), "order_id": order_id}
        self.reports.append(report)
        outcome, payment_id = report["outcome"], report["payment_id"]
        if outcome == "SUCCEEDED":
            if order["status"] == "PAID":
                if order["payment_id"] != payment_id:
                    return httpx.Response(409, json={"error": {"code": "ORDER_ALREADY_PAID"}})
            elif order["status"] != "AWAITING_PAYMENT":
                return httpx.Response(409, json={"error": {"code": "ORDER_NOT_FULFILLABLE"}})
            else:
                order.update(status="PAID", payment_id=payment_id)
        elif outcome == "REFUNDED" and order["payment_id"] == payment_id and order["status"] == "PAID":
            order["status"] = "CANCELLED"
        order["payment_status"] = outcome
        return httpx.Response(200, json={"order_id": order_id, "status": order["status"], "payment_status": outcome})
