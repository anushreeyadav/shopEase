"""Order API and checkout coordination tests (SQLite file DB + fake dependencies)."""

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.config import Settings
from app.db import Database
from app.main import create_app
from app.models import Base, Order, OrderStatus
from app.models.base import utcnow
from app.orders import recover
from app.state import ALLOWED, can_transition
from tests.fakes import SERVICE_TOKEN, FakeDependencies
from tests.jwt_helpers import KEY_PROVIDER, bearer, make_token

PAYMENT_SVC = bearer(make_token("svc:payment", token_use="service", scope="orders:read orders:payment"))


class Customer:
    def __init__(self, client: TestClient, deps: FakeDependencies, role: str = "customer"):
        self.id = uuid.uuid4()
        self.token = make_token(self.id, role=role)
        self.headers = bearer(self.token)
        self.client, self.deps = client, deps
        self.address_id = deps.add_address(self.id)

    def order(self, items, key=None, address_id=None, **extra):
        body = {"items": [{"product_id": p, "quantity": q} for p, q in items],
                "shipping_address_id": address_id or self.address_id, **extra}
        headers = {**self.headers, "Idempotency-Key": key or str(uuid.uuid4())}
        return self.client.post("/api/orders", headers=headers, json=body)

    def get(self, path, **kw):
        return self.client.get(path, headers=self.headers, **kw)

    def cancel(self, order_id):
        return self.client.post(f"/api/orders/{order_id}/cancel", headers=self.headers)


class Ctx:
    def __init__(self, client, deps, db, settings):
        self.client, self.deps, self.db, self.settings = client, deps, db, settings

    def customer(self, role="customer") -> Customer:
        return Customer(self.client, self.deps, role)

    def pay(self, order_id, outcome="SUCCEEDED", payment_id=None):
        return self.client.post(
            f"/internal/orders/{order_id}/payment-result", headers=PAYMENT_SVC,
            json={"payment_id": str(payment_id or uuid.uuid4()), "outcome": outcome},
        )

    def recover(self):
        with self.db.session() as session:
            return recover(session, self.client.app.state.clients, self.settings)

    def stored_orders(self) -> int:
        with self.db.session() as session:
            return session.query(Order).count()


@pytest.fixture
def ctx(tmp_path):
    db_file = tmp_path / "orders.db"
    deps = FakeDependencies(db_path=str(db_file))
    settings = Settings(_env_file=None, APP_ENV="test", ORDER_SWEEP_SECONDS=0, ORDER_SERVICE_CLIENT_SECRET="s3cret")
    app = create_app(settings, key_provider=KEY_PROVIDER, transport=deps.transport)
    db = Database(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(db.engine)
    app.state.db = db
    with TestClient(app, raise_server_exceptions=False) as client:
        yield Ctx(client, deps, db, settings)
    assert deps.lock_violations == [], f"DB write transaction open during calls: {deps.lock_violations}"
    db.dispose()


def code(response) -> str:
    return response.json()["error"]["code"]


# --- Successful checkout ----------------------------------------------------------------------


def test_successful_checkout_uses_server_side_prices_and_snapshots(ctx):
    shoe = ctx.deps.add_product("Trail Running Shoe", "2499.00", stock=5)
    socks = ctx.deps.add_product("Running Socks 3-Pack", "299.00", stock=10)
    customer = ctx.customer()

    response = customer.order([(shoe, 1), (socks, 2)])
    assert response.status_code == 201, response.text
    body = response.json()
    assert response.headers["Location"] == f"/api/orders/{body['order_id']}"
    assert body["status"] == "AWAITING_PAYMENT" and body["payment_status"] == "NONE"
    assert body["total_amount"] == "3097.00" and body["currency"] == "INR"
    lines = {i["name"]: (i["unit_price"], i["quantity"], i["line_total"]) for i in body["items"]}
    assert lines == {"Trail Running Shoe": ("2499.00", 1, "2499.00"), "Running Socks 3-Pack": ("299.00", 2, "598.00")}
    assert body["shipping_address"]["city"] == "Pune" and "address_id" not in body["shipping_address"]
    assert body["payment_due_by"] is not None
    assert [(h["from_status"], h["to_status"]) for h in body["status_history"]] == [
        (None, "PENDING"), ("PENDING", "AWAITING_PAYMENT")]
    assert ctx.deps.available(shoe) == 4 and ctx.deps.available(socks) == 8

    # Calls carried the service token, and the address lookup carried the customer's token.
    _, address_call = next(c for c in ctx.deps.calls if c[0] == "address")
    assert address_call.headers["X-User-Token"] == customer.token
    assert all(r.headers.get("Authorization") == f"Bearer {SERVICE_TOKEN}" for op, r in ctx.deps.calls if op != "token")
    assert ctx.deps.count("token") == 1  # cached

    # A later price change does not alter the stored order.
    ctx.deps.products[shoe]["price"] = "9999.00"
    assert customer.get(f"/api/orders/{body['order_id']}").json()["total_amount"] == "3097.00"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["items"][0].update(unit_price="1.00"),
        lambda b: b.update(total_amount="1.00"),
        lambda b: b["items"].append(dict(b["items"][0])),
        lambda b: b["items"][0].update(quantity=0),
        lambda b: b.update(items=[]),
        lambda b: b.update(user_id=str(uuid.uuid4())),
    ],
    ids=["client-price", "client-total", "duplicate-product", "zero-quantity", "no-items", "client-user-id"],
)
def test_client_cannot_supply_prices_totals_or_identity(ctx, mutate):
    pid = ctx.deps.add_product("Shoe", "10.00", stock=5)
    customer = ctx.customer()
    body = {"items": [{"product_id": pid, "quantity": 1}], "shipping_address_id": customer.address_id}
    mutate(body)
    response = ctx.client.post("/api/orders", headers={**customer.headers, "Idempotency-Key": "key-12345678"}, json=body)
    assert response.status_code == 422 and code(response) == "VALIDATION_ERROR"
    assert ctx.stored_orders() == 0


@pytest.mark.parametrize("key", [None, "short", "has space in it", "x" * 65])
def test_idempotency_key_is_required_and_validated(ctx, key):
    pid = ctx.deps.add_product("Shoe", "10.00", stock=5)
    customer = ctx.customer()
    headers = dict(customer.headers) | ({"Idempotency-Key": key} if key else {})
    response = ctx.client.post("/api/orders", headers=headers,
                               json={"items": [{"product_id": pid, "quantity": 1}], "shipping_address_id": customer.address_id})
    assert response.status_code == 422


# --- Stock and catalog problems -------------------------------------------------------------


def test_insufficient_stock_is_rejected_before_anything_is_stored(ctx):
    pid = ctx.deps.add_product("Shoe", "10.00", stock=2)
    customer = ctx.customer()
    response = customer.order([(pid, 3)], key="order-key-1")
    assert response.status_code == 409 and code(response) == "OUT_OF_STOCK"
    assert response.json()["error"]["details"][0]["issue"] == "exceeds available stock (2)"
    assert ctx.stored_orders() == 0 and ctx.deps.count("reserve") == 0

    ctx.deps.products[pid]["stock"] = 5  # restocked: the same key may be used again
    assert customer.order([(pid, 3)], key="order-key-1").status_code == 201


def test_stock_lost_between_price_check_and_reservation_cancels_the_order(ctx):
    pid = ctx.deps.add_product("Shoe", "10.00", stock=3)
    customer = ctx.customer()
    ctx.deps.fail("price_check")  # no failure; make reserve see less stock:
    original = ctx.deps._reserve

    def racing_reserve(request, path):
        ctx.deps.products[pid]["reserved"] = 3  # another buyer took the stock
        return original(request, path)

    ctx.deps._reserve = racing_reserve
    response = customer.order([(pid, 1)], key="race-key-0001")
    assert response.status_code == 409 and code(response) == "OUT_OF_STOCK"
    [summary] = customer.get("/api/orders").json()["items"]
    assert summary["status"] == "CANCELLED"
    detail = customer.get(f"/api/orders/{summary['order_id']}").json()
    assert detail["cancel_reason"] == "OUT_OF_STOCK" and ctx.deps.count("release") == 0
    replay = customer.order([(pid, 1)], key="race-key-0001")
    assert replay.status_code == 409 and code(replay) == "OUT_OF_STOCK"


def test_unknown_archived_and_foreign_address_errors(ctx):
    pid = ctx.deps.add_product("Shoe", "10.00", stock=5)
    old = ctx.deps.add_product("Old", "10.00", stock=5, status="ARCHIVED")
    customer, other = ctx.customer(), ctx.customer()
    missing = customer.order([(str(uuid.uuid4()), 1)])
    assert missing.status_code == 404 and code(missing) == "PRODUCT_NOT_FOUND"
    archived = customer.order([(old, 1)])
    assert archived.status_code == 409 and code(archived) == "PRODUCT_UNAVAILABLE"
    foreign = customer.order([(pid, 1)], address_id=other.address_id)
    assert foreign.status_code == 404 and code(foreign) == "ADDRESS_NOT_FOUND"
    usd = ctx.deps.add_product("Import", "5.00", stock=5, currency="USD")
    mixed = customer.order([(pid, 1), (usd, 1)])
    assert mixed.status_code == 409 and code(mixed) == "MIXED_CURRENCY"
    assert ctx.stored_orders() == 0 and ctx.deps.available(pid) == 5


# --- Dependency timeouts and failures ---------------------------------------------------------


def test_catalog_timeout_retries_once_then_fails_without_storing(ctx):
    pid = ctx.deps.add_product("Shoe", "10.00", stock=5)
    ctx.deps.fail("price_check", "timeout", "timeout")
    response = ctx.customer().order([(pid, 1)])
    assert response.status_code == 504 and code(response) == "DEPENDENCY_TIMEOUT"
    assert ctx.deps.count("price_check") == 2 and ctx.stored_orders() == 0


def test_connection_failures_are_retried_once(ctx):
    pid = ctx.deps.add_product("Shoe", "10.00", stock=5)
    ctx.deps.fail("price_check", "connect")
    ctx.deps.fail("address", 503)
    assert ctx.customer().order([(pid, 1)]).status_code == 201
    assert ctx.deps.count("price_check") == 2 and ctx.deps.count("address") == 2


def test_user_service_down_gives_503(ctx):
    pid = ctx.deps.add_product("Shoe", "10.00", stock=5)
    ctx.deps.fail("address", 503, 503)
    response = ctx.customer().order([(pid, 1)])
    assert response.status_code == 503 and code(response) == "DEPENDENCY_UNAVAILABLE"
    assert ctx.stored_orders() == 0


def test_reservation_timeout_is_compensated_by_releasing_stock(ctx):
    pid = ctx.deps.add_product("Shoe", "10.00", stock=5)
    customer = ctx.customer()
    # The first attempt reserves stock but the answer is lost; the retry also times out.
    ctx.deps.fail("reserve", "apply_then_timeout", "timeout")
    response = customer.order([(pid, 2)], key="timeout-key-1")
    assert response.status_code == 504 and code(response) == "DEPENDENCY_TIMEOUT"
    assert "new Idempotency-Key" in response.json()["error"]["message"]
    assert ctx.deps.count("release") == 1 and ctx.deps.available(pid) == 5  # stock returned

    [summary] = customer.get("/api/orders").json()["items"]
    detail = customer.get(f"/api/orders/{summary['order_id']}").json()
    assert detail["status"] == "CANCELLED" and detail["cancel_reason"] == "DEPENDENCY_TIMEOUT"
    replay = customer.order([(pid, 2)], key="timeout-key-1")
    assert replay.status_code == 503 and code(replay) == "ORDER_NOT_PLACED"
    assert customer.order([(pid, 2)], key="timeout-key-2").status_code == 201


def test_failed_compensation_is_retried_by_the_recovery_job(ctx):
    pid = ctx.deps.add_product("Shoe", "10.00", stock=5)
    ctx.deps.fail("reserve", "apply_then_timeout", "timeout")
    ctx.deps.fail("release", "timeout", "timeout")
    assert ctx.customer().order([(pid, 2)]).status_code == 504
    assert ctx.deps.available(pid) == 3  # still held: release failed
    with ctx.db.session() as session:
        assert session.query(Order).one().release_pending is True

    assert ctx.recover()["released"] == 1
    assert ctx.deps.available(pid) == 5
    with ctx.db.session() as session:
        assert session.query(Order).one().release_pending is False


def test_auth_service_unavailable_for_service_token(ctx):
    pid = ctx.deps.add_product("Shoe", "10.00", stock=5)
    ctx.deps.fail("token", 503, 503)
    response = ctx.customer().order([(pid, 1)])
    assert response.status_code == 503 and ctx.stored_orders() == 0


# --- Repeated submissions -----------------------------------------------------------------------


def test_repeated_submissions_create_one_order_and_reserve_once(ctx):
    pid = ctx.deps.add_product("Shoe", "10.00", stock=5)
    customer, other = ctx.customer(), ctx.customer()
    first = customer.order([(pid, 1)], key="same-key-0001")
    again = customer.order([(pid, 1)], key="same-key-0001")
    assert first.status_code == again.status_code == 201
    assert again.json()["order_id"] == first.json()["order_id"]
    assert again.headers["Idempotent-Replayed"] == "true"
    assert ctx.deps.count("reserve") == 1 and ctx.deps.available(pid) == 4

    different = customer.order([(pid, 2)], key="same-key-0001")
    assert different.status_code == 409 and code(different) == "IDEMPOTENCY_KEY_REUSED"
    assert other.order([(pid, 1)], key="same-key-0001").status_code == 201  # keys are per user
    assert customer.order([(pid, 1)], key="same-key-0002").status_code == 201  # new intent
    assert ctx.stored_orders() == 3


def test_request_in_progress_is_reported_for_a_pending_replay(ctx):
    pid = ctx.deps.add_product("Shoe", "10.00", stock=5)
    customer = ctx.customer()
    ctx.deps.fail("reserve", "apply_then_timeout", "timeout")
    ctx.deps.fail("release", "timeout", "timeout")
    customer.order([(pid, 1)], key="pending-key-1")
    with ctx.db.session() as session:  # simulate a crash that left the order PENDING
        session.execute(update(Order).values(status=OrderStatus.PENDING))
        session.commit()
    replay = customer.order([(pid, 1)], key="pending-key-1")
    assert replay.status_code == 409 and code(replay) == "REQUEST_IN_PROGRESS"


# --- Payment outcomes (reported by payment_service, ADR-13) ------------------------------------


@pytest.fixture
def placed(ctx):
    pid = ctx.deps.add_product("Shoe", "2499.00", stock=5)
    customer = ctx.customer()
    order = customer.order([(pid, 2)]).json()
    return ctx, customer, order["order_id"], pid


def test_payable_view_is_authoritative(placed):
    ctx, customer, order_id, _ = placed
    view = ctx.client.get(f"/internal/orders/{order_id}/payable", headers=PAYMENT_SVC).json()
    assert view["amount"] == "4998.00" and view["user_id"] == str(customer.id) and view["payable"] is True
    assert ctx.client.get(f"/internal/orders/{uuid.uuid4()}/payable", headers=PAYMENT_SVC).status_code == 404


def test_payment_success_confirms_stock_and_is_idempotent(placed):
    ctx, customer, order_id, pid = placed
    payment = uuid.uuid4()
    first = ctx.pay(order_id, "SUCCEEDED", payment)
    assert first.status_code == 200 and first.json()["status"] == "PAID"
    assert ctx.deps.products[pid]["stock"] == 3 and ctx.deps.products[pid]["reserved"] == 0
    assert ctx.pay(order_id, "SUCCEEDED", payment).status_code == 200  # repeated report
    assert ctx.deps.products[pid]["stock"] == 3  # deducted once
    duplicate = ctx.pay(order_id, "SUCCEEDED", uuid.uuid4())
    assert duplicate.status_code == 409 and code(duplicate) == "ORDER_ALREADY_PAID"
    detail = customer.get(f"/api/orders/{order_id}").json()
    assert detail["payment_id"] == str(payment) and detail["payment_status"] == "SUCCEEDED"


def test_payment_decline_keeps_the_order_payable(placed):
    ctx, customer, order_id, pid = placed
    declined = ctx.pay(order_id, "FAILED")
    assert declined.json() == {"order_id": order_id, "status": "AWAITING_PAYMENT", "payment_status": "FAILED"}
    assert ctx.deps.available(pid) == 3  # still reserved for a retry
    assert ctx.client.get(f"/internal/orders/{order_id}/payable", headers=PAYMENT_SVC).json()["payable"] is True
    assert ctx.pay(order_id, "SUCCEEDED").json()["status"] == "PAID"


def test_uncertain_payment_blocks_cancellation_and_waits_for_reconciliation(placed):
    ctx, customer, order_id, pid = placed
    assert ctx.pay(order_id, "PROCESSING").json()["payment_status"] == "PROCESSING"
    blocked = customer.cancel(order_id)
    assert blocked.status_code == 409 and code(blocked) == "PAYMENT_IN_PROGRESS"
    assert ctx.deps.count("release") == 0
    assert ctx.pay(order_id, "SUCCEEDED").json()["status"] == "PAID"  # reconciliation result


def test_success_after_reservation_expired_asks_for_a_refund(placed):
    ctx, customer, order_id, pid = placed
    ctx.deps.expire_reservation(order_id)
    payment = uuid.uuid4()
    late = ctx.pay(order_id, "SUCCEEDED", payment)
    assert late.status_code == 409 and code(late) == "ORDER_NOT_FULFILLABLE"
    detail = customer.get(f"/api/orders/{order_id}").json()
    assert detail["status"] == "CANCELLED" and detail["cancel_reason"] == "RESERVATION_EXPIRED"
    assert detail["payment_status"] == "SUCCEEDED"  # charged; payment_service refunds next
    assert detail["payment_id"] == str(payment)
    assert ctx.deps.available(pid) == 5
    assert code(ctx.pay(order_id, "SUCCEEDED", payment)) == "ORDER_NOT_FULFILLABLE"  # same answer on repeat
    refunded = ctx.pay(order_id, "REFUNDED", payment)
    assert refunded.json()["payment_status"] == "REFUNDED"


def test_confirm_timeout_leaves_the_order_unchanged_for_a_retry(placed):
    ctx, customer, order_id, pid = placed
    ctx.deps.fail("confirm", "timeout", "timeout")
    payment = uuid.uuid4()
    response = ctx.pay(order_id, "SUCCEEDED", payment)
    assert response.status_code == 504
    assert customer.get(f"/api/orders/{order_id}").json()["status"] == "AWAITING_PAYMENT"
    assert ctx.pay(order_id, "SUCCEEDED", payment).json()["status"] == "PAID"


def test_payment_after_customer_cancellation_is_refused(placed):
    ctx, customer, order_id, pid = placed
    assert customer.cancel(order_id).json()["status"] == "CANCELLED"
    assert ctx.deps.available(pid) == 5
    late = ctx.pay(order_id, "SUCCEEDED")
    assert late.status_code == 409 and code(late) == "ORDER_NOT_FULFILLABLE"


def test_refund_of_a_paid_order_cancels_it(placed):
    ctx, customer, order_id, _ = placed
    payment = uuid.uuid4()
    ctx.pay(order_id, "SUCCEEDED", payment)
    result = ctx.pay(order_id, "REFUNDED", payment).json()
    assert result == {"order_id": order_id, "status": "CANCELLED", "payment_status": "REFUNDED"}


def test_internal_endpoints_require_the_right_service_scope(placed):
    ctx, customer, order_id, _ = placed
    path = f"/internal/orders/{order_id}/payment-result"
    body = {"payment_id": str(uuid.uuid4()), "outcome": "SUCCEEDED"}
    assert ctx.client.post(path, headers=customer.headers, json=body).status_code == 401
    read_only = bearer(make_token("svc:payment", token_use="service", scope="orders:read"))
    denied = ctx.client.post(path, headers=read_only, json=body)
    assert denied.status_code == 403 and code(denied) == "INSUFFICIENT_SCOPE"
    assert ctx.client.get(f"/internal/orders/{order_id}/payable", headers=customer.headers).status_code == 401
    assert customer.get(f"/api/orders/{order_id}").json()["status"] == "AWAITING_PAYMENT"


# --- Ownership -------------------------------------------------------------------------------------


def test_customers_see_only_their_own_orders(ctx):
    pid = ctx.deps.add_product("Shoe", "10.00", stock=10)
    alice, bob, admin = ctx.customer(), ctx.customer(), ctx.customer(role="admin")
    alice_order = alice.order([(pid, 1)]).json()["order_id"]
    bob.order([(pid, 2)])

    hidden = bob.get(f"/api/orders/{alice_order}")
    assert hidden.status_code == 404 and code(hidden) == "ORDER_NOT_FOUND"
    assert bob.cancel(alice_order).status_code == 404
    assert alice.get(f"/api/orders/{alice_order}").status_code == 200
    mine = bob.get("/api/orders").json()
    assert mine["total"] == 1 and mine["items"][0]["item_count"] == 2
    assert bob.get("/api/orders", params={"user_id": str(alice.id)}).status_code == 403

    assert admin.get(f"/api/orders/{alice_order}").status_code == 200
    assert admin.get("/api/orders").json()["total"] == 2
    assert admin.get("/api/orders", params={"user_id": str(alice.id)}).json()["total"] == 1
    assert alice.get(f"/api/orders/{alice_order}").json()["status"] == "AWAITING_PAYMENT"


# --- State conflicts -------------------------------------------------------------------------------


def test_order_state_conflicts(placed):
    ctx, customer, order_id, _ = placed
    admin = ctx.customer(role="admin")
    ship = lambda who, status: ctx.client.patch(  # noqa: E731
        f"/api/orders/{order_id}/status", headers=who.headers, json={"status": status})

    early = ship(admin, "SHIPPED")
    assert early.status_code == 409 and code(early) == "INVALID_STATUS_TRANSITION"
    assert ship(customer, "SHIPPED").status_code == 403
    assert ship(admin, "PAID").status_code == 422  # PAID only comes from a payment

    ctx.pay(order_id, "SUCCEEDED")
    paid_cancel = customer.cancel(order_id)
    assert paid_cancel.status_code == 409 and code(paid_cancel) == "INVALID_STATUS_TRANSITION"
    assert ship(admin, "SHIPPED").json()["status"] == "SHIPPED"
    assert ship(admin, "DELIVERED").json()["status"] == "DELIVERED"
    assert ship(admin, "SHIPPED").status_code == 409
    history = [h["to_status"] for h in customer.get(f"/api/orders/{order_id}").json()["status_history"]]
    assert history == ["PENDING", "AWAITING_PAYMENT", "PAID", "SHIPPED", "DELIVERED"]


def test_cancel_twice_is_a_conflict(placed):
    ctx, customer, order_id, _ = placed
    assert customer.cancel(order_id).status_code == 200
    again = customer.cancel(order_id)
    assert again.status_code == 409 and code(again) == "INVALID_STATUS_TRANSITION"
    assert ctx.deps.count("release") == 1


def test_cancel_when_inventory_is_down_changes_nothing(placed):
    ctx, customer, order_id, _ = placed
    ctx.deps.fail("release", "timeout", "timeout")
    assert customer.cancel(order_id).status_code == 504
    assert customer.get(f"/api/orders/{order_id}").json()["status"] == "AWAITING_PAYMENT"


def test_state_machine_matrix():
    S = OrderStatus
    expected = {
        (None, S.PENDING), (S.PENDING, S.AWAITING_PAYMENT), (S.PENDING, S.CANCELLED),
        (S.AWAITING_PAYMENT, S.PAID), (S.AWAITING_PAYMENT, S.CANCELLED),
        (S.PAID, S.SHIPPED), (S.PAID, S.CANCELLED), (S.SHIPPED, S.DELIVERED),
    }
    actual = {(a, b) for a in [None, *S] for b in S if can_transition(a, b)}
    assert actual == expected
    assert ALLOWED[S.DELIVERED] == ALLOWED[S.CANCELLED] == frozenset()


# --- Recovery job ------------------------------------------------------------------------------------


def test_recovery_expires_unpaid_orders_and_cleans_up_abandoned_ones(placed):
    ctx, customer, order_id, pid = placed
    paid_id = customer.order([(pid, 1)]).json()["order_id"]
    ctx.pay(paid_id, "SUCCEEDED")
    with ctx.db.session() as session:
        session.execute(update(Order).values(payment_due_by=utcnow() - timedelta(minutes=1)))
        stuck = Order(user_id=customer.id, total_amount=1, currency="INR", shipping_address_snapshot={},
                      idempotency_key="stuck-key-01", request_fingerprint="f" * 64, status=OrderStatus.PENDING)
        session.add(stuck)
        session.flush()
        session.execute(update(Order).where(Order.id == stuck.id).values(created_at=utcnow() - timedelta(hours=1)))
        session.commit()

    counts = ctx.recover()
    assert counts["expired"] == 1 and counts["stuck"] == 1
    expired = customer.get(f"/api/orders/{order_id}").json()
    assert expired["status"] == "CANCELLED" and expired["cancel_reason"] == "PAYMENT_TIMEOUT"
    assert customer.get(f"/api/orders/{paid_id}").json()["status"] == "PAID"  # paid orders untouched
    assert ctx.deps.available(pid) == 4  # 2 released; the paid unit stays sold
    assert ctx.client.get(f"/internal/orders/{order_id}/payable", headers=PAYMENT_SVC).json()["payable"] is False


def test_recovery_leaves_an_order_whose_stock_was_confirmed_meanwhile(placed):
    ctx, customer, order_id, _ = placed
    ctx.deps.reservations[order_id]["status"] = "CONFIRMED"  # payment confirmed; result not yet applied
    with ctx.db.session() as session:
        session.execute(update(Order).values(payment_due_by=utcnow() - timedelta(minutes=1)))
        session.commit()
    assert ctx.recover()["expired"] == 0
    assert customer.get(f"/api/orders/{order_id}").json()["status"] == "AWAITING_PAYMENT"
