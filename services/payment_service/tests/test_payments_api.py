"""Payment API tests with the MOCK provider and a fake order_service (SQLite)."""

import io
import logging
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.config import Settings
from app.db import Database
from app.main import create_app
from app.models import Base, Payment
from app.models.base import utcnow
from app.payments import run_background
from app.providers.mock import MockProvider
from shopease_shared.log_config import JsonFormatter
from tests.fakes import FakeOrders
from tests.jwt_helpers import KEY_PROVIDER, bearer, make_token

RECONCILER = bearer(make_token("svc:ops", token_use="service", scope="payments:reconcile"))


class Customer:
    def __init__(self, ctx, role="customer"):
        self.id = uuid.uuid4()
        self.headers = bearer(make_token(self.id, role=role))
        self.ctx = ctx

    def pay(self, order_id, token="mock_tok_success", key=None, **extra):
        headers = {**self.headers, "Idempotency-Key": key or str(uuid.uuid4())}
        return self.ctx.client.post("/api/payments", headers=headers,
                                    json={"order_id": str(order_id), "payment_method_token": token, **extra})

    def get(self, path, **kw):
        return self.ctx.client.get(path, headers=self.headers, **kw)


class Ctx:
    def __init__(self, client, orders, provider, db):
        self.client, self.orders, self.provider, self.db = client, orders, provider, db

    def customer(self, role="customer") -> Customer:
        return Customer(self, role)

    def background(self, make_due=True):
        if make_due:
            with self.db.session() as session:
                session.execute(update(Payment).values(next_reconcile_at=utcnow(), next_report_at=utcnow()))
                session.commit()
        with self.db.session() as session:
            return run_background(session, self.client.app.state.payment_ctx)

    def payment_row(self, payment_id) -> Payment:
        with self.db.session() as session:
            return session.get(Payment, uuid.UUID(payment_id))

    def charges(self, payment_id) -> int:
        return self.provider.charge_calls.get(str(payment_id), 0)


@pytest.fixture
def ctx(tmp_path):
    orders, provider = FakeOrders(), MockProvider()
    settings = Settings(_env_file=None, APP_ENV="test", PAYMENT_SWEEP_SECONDS=0, PAYMENT_SERVICE_CLIENT_SECRET="s3cret")
    app = create_app(settings, key_provider=KEY_PROVIDER, transport=orders.transport, provider=provider)
    db = Database(f"sqlite:///{tmp_path / 'payments.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(db.engine)
    app.state.db = db
    with TestClient(app, raise_server_exceptions=False) as client:
        yield Ctx(client, orders, provider, db)
    db.dispose()


def code(response) -> str:
    return response.json()["error"]["code"]


# --- Successful mock payment ----------------------------------------------------------------------


def test_successful_mock_payment(ctx):
    customer = ctx.customer()
    order_id = ctx.orders.add_order(customer.id, amount="3097.00")
    response = customer.pay(order_id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert response.headers["Location"] == f"/api/payments/{body['payment_id']}"
    assert body["status"] == "SUCCEEDED" and body["amount"] == "3097.00" and body["currency"] == "INR"
    assert body["provider"] == "mock" and body["provider_reference"].startswith("mock_txn_")
    assert body["payment_method"] == {"type": "card", "brand": "MOCKVISA", "last4": "0000"}
    assert [(h["from_status"], h["to_status"], h["source"]) for h in body["status_history"]] == [
        (None, "INITIATED", "API"), ("INITIATED", "SUCCEEDED", "API")]
    assert ctx.orders.outcomes(order_id) == ["SUCCEEDED"] and ctx.orders.orders[order_id]["status"] == "PAID"
    assert ctx.payment_row(body["payment_id"]).result_reported_at is not None
    assert ctx.charges(body["payment_id"]) == 1

    assert customer.get(f"/api/payments/{body['payment_id']}").json()["status"] == "SUCCEEDED"
    listing = customer.get("/api/payments", params={"order_id": order_id}).json()
    assert listing["total"] == 1 and listing["items"][0]["payment_id"] == body["payment_id"]


def test_amount_always_comes_from_the_order(ctx):
    customer = ctx.customer()
    order_id = ctx.orders.add_order(customer.id, amount="10.00")
    response = ctx.client.post("/api/payments", headers={**customer.headers, "Idempotency-Key": "key-amount-1"},
                               json={"order_id": order_id, "payment_method_token": "mock_tok_success", "amount": "1.00"})
    assert response.status_code == 422  # no client-supplied amount field
    assert customer.pay(order_id).json()["amount"] == "10.00"


# --- Declines ----------------------------------------------------------------------------------


@pytest.mark.parametrize("token,reason", [("mock_tok_decline", "card_declined"),
                                          ("mock_tok_insufficient_funds", "insufficient_funds")])
def test_declined_payment(ctx, token, reason):
    customer = ctx.customer()
    order_id = ctx.orders.add_order(customer.id)
    declined = customer.pay(order_id, token)
    assert declined.status_code == 422 and code(declined) == "PAYMENT_DECLINED"
    [summary] = customer.get("/api/payments", params={"order_id": order_id}).json()["items"]
    detail = customer.get(f"/api/payments/{summary['payment_id']}").json()
    assert detail["status"] == "FAILED" and detail["failure_reason"] == reason
    assert ctx.orders.outcomes(order_id) == ["FAILED"]
    # The order is free for another attempt with a new key.
    assert customer.pay(order_id).status_code == 201


# --- Idempotency -----------------------------------------------------------------------------------


def test_repeated_idempotency_key_never_charges_twice(ctx):
    customer, other = ctx.customer(), ctx.customer()
    order_id = ctx.orders.add_order(customer.id)
    first = customer.pay(order_id, key="pay-key-0001")
    again = customer.pay(order_id, key="pay-key-0001")
    assert first.status_code == again.status_code == 201
    assert again.json()["payment_id"] == first.json()["payment_id"]
    assert ctx.charges(first.json()["payment_id"]) == 1
    assert ctx.orders.outcomes(order_id) == ["SUCCEEDED"]

    changed = customer.pay(order_id, token="mock_tok_decline", key="pay-key-0001")
    assert changed.status_code == 409 and code(changed) == "IDEMPOTENCY_KEY_REUSED"
    stolen = other.pay(order_id, key="pay-key-0001")
    assert stolen.status_code == 409 and "SUCCEEDED" not in stolen.text  # nothing leaked

    declined_key = ctx.orders.add_order(customer.id)
    assert customer.pay(declined_key, "mock_tok_decline", key="pay-key-0002").status_code == 422
    assert customer.pay(declined_key, "mock_tok_decline", key="pay-key-0002").status_code == 422  # same answer


def test_idempotency_key_uniqueness_is_enforced_in_storage(ctx):
    customer = ctx.customer()
    order_id = ctx.orders.add_order(customer.id)
    payment_id = customer.pay(order_id, key="db-unique-01").json()["payment_id"]
    from sqlalchemy.exc import IntegrityError

    with ctx.db.session() as session:
        original = session.get(Payment, uuid.UUID(payment_id))
        session.add(Payment(order_id=uuid.uuid4(), user_id=customer.id, amount=1, currency="INR", provider="mock",
                            idempotency_key=original.idempotency_key, request_fingerprint="x" * 64))
        with pytest.raises(IntegrityError):
            session.commit()


def test_only_one_active_payment_per_order(ctx):
    customer = ctx.customer()
    order_id = ctx.orders.add_order(customer.id)
    pending = customer.pay(order_id, "mock_tok_pending")
    assert pending.status_code == 202
    second = customer.pay(order_id, "mock_tok_success")
    assert second.status_code == 409 and code(second) == "PAYMENT_ALREADY_IN_PROGRESS"


# --- Amount and order validation -------------------------------------------------------------------


def test_mismatched_amounts_and_currency_are_rejected_before_charging(ctx):
    customer = ctx.customer()
    order_id = ctx.orders.add_order(customer.id, amount="3097.00")
    wrong = customer.pay(order_id, expected_amount="2999.00")
    assert wrong.status_code == 409 and code(wrong) == "AMOUNT_MISMATCH"
    currency = customer.pay(order_id, expected_amount="3097.00", currency="USD")
    assert currency.status_code == 409 and code(currency) == "CURRENCY_MISMATCH"
    assert ctx.provider.charge_calls == {}
    assert customer.pay(order_id, expected_amount="3097.00", currency="INR").status_code == 201


def test_provider_amount_mismatch_is_never_reported_as_success(ctx):
    customer = ctx.customer()
    order_id = ctx.orders.add_order(customer.id)
    response = customer.pay(order_id, "mock_tok_amount_mismatch")
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "PROCESSING" and body["requires_review"] is True
    assert body["failure_reason"] == "provider_amount_mismatch"
    assert "SUCCEEDED" not in ctx.orders.outcomes(order_id)


@pytest.mark.parametrize("status", ["PAID", "CANCELLED"])
def test_unpayable_orders_are_not_charged(ctx, status):
    customer = ctx.customer()
    order_id = ctx.orders.add_order(customer.id)
    ctx.orders.orders[order_id]["status"] = status
    response = customer.pay(order_id)
    assert response.status_code == 409 and code(response) == "ORDER_NOT_PAYABLE"
    assert ctx.provider.charge_calls == {}


def test_unknown_order_and_order_service_down(ctx):
    customer = ctx.customer()
    assert code(customer.pay(uuid.uuid4())) == "ORDER_NOT_FOUND"
    order_id = ctx.orders.add_order(customer.id)
    ctx.orders.fail("payable", "timeout", "timeout")
    down = customer.pay(order_id)
    assert down.status_code == 504 and "nothing was charged" in down.json()["error"]["message"]
    assert ctx.provider.charge_calls == {}


# --- Authorization ------------------------------------------------------------------------------


def test_unauthorized_callers(ctx):
    owner, stranger, admin = ctx.customer(), ctx.customer(), ctx.customer(role="admin")
    order_id = ctx.orders.add_order(owner.id)

    no_token = ctx.client.post("/api/payments", headers={"Idempotency-Key": "anon-key-01"},
                               json={"order_id": order_id, "payment_method_token": "mock_tok_success"})
    assert no_token.status_code == 401
    service = bearer(make_token("svc:order", token_use="service", scope="orders:read"))
    assert ctx.client.post("/api/payments", headers={**service, "Idempotency-Key": "svc-key-001"},
                           json={"order_id": order_id, "payment_method_token": "mock_tok_success"}).status_code == 401
    foreign = stranger.pay(order_id)
    assert foreign.status_code == 404 and code(foreign) == "ORDER_NOT_FOUND"
    assert ctx.provider.charge_calls == {}

    payment_id = owner.pay(order_id).json()["payment_id"]
    assert stranger.get(f"/api/payments/{payment_id}").status_code == 404
    assert stranger.get("/api/payments", params={"order_id": order_id}).json()["total"] == 0
    assert admin.get(f"/api/payments/{payment_id}").status_code == 200

    refund = {"reason": "test"}
    assert ctx.client.post(f"/api/payments/{payment_id}/refunds", headers={**owner.headers, "Idempotency-Key": "rf-key-001"},
                           json=refund).status_code == 403
    path = f"/internal/payments/{payment_id}/reconcile"
    assert ctx.client.post(path, headers=owner.headers).status_code == 401
    wrong_scope = bearer(make_token("svc:order", token_use="service", scope="orders:read"))
    assert code(ctx.client.post(path, headers=wrong_scope)) == "INSUFFICIENT_SCOPE"
    assert ctx.client.post(path, headers=RECONCILER).status_code == 200


def test_card_data_is_rejected_and_never_echoed_or_logged(ctx):
    customer = ctx.customer()
    order_id = ctx.orders.add_order(customer.id)
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(JsonFormatter("payment_service"))
    logging.getLogger().addHandler(handler)
    try:
        pan = customer.pay(order_id, token="4111111111111111")
        embedded = customer.pay(order_id, token="tok_4111111111111111_x")
        unknown = customer.pay(order_id, token="tok_live_real_looking")
        customer.pay(order_id, token="mock_tok_success")
    finally:
        logging.getLogger().removeHandler(handler)
    for response in (pan, embedded):
        assert response.status_code == 422 and "4111111111111111" not in response.text
        assert "card numbers are not accepted" in response.json()["error"]["details"][0]["issue"]
    assert unknown.status_code == 422 and code(unknown) == "INVALID_PAYMENT_METHOD"
    logs = buffer.getvalue()
    assert "payment succeeded" in logs
    for secret in ("4111111111111111", "mock_tok_success", "tok_live_real_looking"):
        assert secret not in logs


# --- Duplicate provider references -------------------------------------------------------------


def test_duplicate_provider_reference_is_not_recorded_as_a_second_success(ctx):
    customer = ctx.customer()
    first_order, second_order = ctx.orders.add_order(customer.id), ctx.orders.add_order(customer.id)
    first = customer.pay(first_order, "mock_tok_duplicate_ref")
    assert first.status_code == 201 and first.json()["provider_reference"] == "mock_txn_duplicate"
    second = customer.pay(second_order, "mock_tok_duplicate_ref")
    assert second.status_code == 202
    body = second.json()
    assert body["status"] == "PROCESSING" and body["requires_review"] is True
    assert body["failure_reason"] == "duplicate_provider_reference" and body["provider_reference"] is None
    assert ctx.orders.outcomes(second_order) == ["PROCESSING"]
    assert customer.get(f"/api/payments/{first.json()['payment_id']}").json()["status"] == "SUCCEEDED"
    # Reconciling it again can't turn it into a success either.
    again = ctx.client.post(f"/internal/payments/{body['payment_id']}/reconcile",
                            params={"include_manual_review": "true"}, headers=RECONCILER).json()
    assert again["status"] == "PROCESSING" and again["requires_review"] is True


# --- Uncertain results and reconciliation -----------------------------------------------------------


def test_timeout_is_an_unknown_outcome_resolved_by_reconciliation(ctx):
    customer = ctx.customer()
    order_id = ctx.orders.add_order(customer.id)
    response = customer.pay(order_id, "mock_tok_timeout", key="timeout-key-1")
    assert response.status_code == 202
    payment_id = response.json()["payment_id"]
    assert response.json()["status"] == "PROCESSING" and response.json()["requires_review"] is False
    assert ctx.orders.outcomes(order_id) == ["PROCESSING"]  # order shows payment in progress

    retry = customer.pay(order_id, "mock_tok_timeout", key="timeout-key-1")
    assert retry.status_code == 202 and retry.json()["payment_id"] == payment_id
    new_key = customer.pay(order_id, "mock_tok_success", key="timeout-key-2")
    assert new_key.status_code == 409 and code(new_key) == "PAYMENT_ALREADY_IN_PROGRESS"
    assert ctx.charges(payment_id) == 1  # never charged again

    assert ctx.background()["reconciled"] == 1
    detail = customer.get(f"/api/payments/{payment_id}").json()
    assert detail["status"] == "SUCCEEDED"
    assert [h["source"] for h in detail["status_history"]] == ["API", "API", "RECONCILIATION"]
    assert ctx.orders.outcomes(order_id) == ["PROCESSING", "SUCCEEDED"]
    assert ctx.charges(payment_id) == 1


def test_timeout_that_was_actually_declined_reconciles_to_failed(ctx):
    customer = ctx.customer()
    order_id = ctx.orders.add_order(customer.id)
    payment_id = customer.pay(order_id, "mock_tok_timeout_declined").json()["payment_id"]
    reconciled = ctx.client.post(f"/internal/payments/{payment_id}/reconcile", headers=RECONCILER).json()
    assert reconciled["status"] == "FAILED" and reconciled["failure_reason"] == "card_declined"
    assert customer.pay(order_id).status_code == 201  # the order can be paid again


def test_unresolved_payment_goes_to_manual_review_after_the_schedule(ctx):
    customer = ctx.customer()
    order_id = ctx.orders.add_order(customer.id)
    payment_id = customer.pay(order_id, "mock_tok_pending").json()["payment_id"]
    for _ in range(6):
        ctx.background()
    row = ctx.payment_row(payment_id)
    assert row.status.value == "PROCESSING" and row.needs_manual_review is True and row.reconcile_attempts == 6
    assert ctx.background()["reconciled"] == 0  # automatic handling stopped
    assert customer.pay(order_id).status_code == 409  # still blocks a second charge


def test_provider_unknown_after_restart_means_never_charged(ctx):
    customer = ctx.customer()
    order_id = ctx.orders.add_order(customer.id)
    payment_id = customer.pay(order_id, "mock_tok_timeout").json()["payment_id"]
    ctx.provider._charges.clear()  # the mock forgets everything when its process restarts
    result = ctx.client.post(f"/internal/payments/{payment_id}/reconcile", headers=RECONCILER).json()
    assert result["status"] == "FAILED" and result["failure_reason"] == "not_found_at_provider"


def test_provider_unavailable_charges_nothing(ctx):
    customer = ctx.customer()
    order_id = ctx.orders.add_order(customer.id)
    response = customer.pay(order_id, "mock_tok_unavailable", key="unavail-key-1")
    assert response.status_code == 503 and code(response) == "PAYMENT_PROVIDER_UNAVAILABLE"
    assert ctx.orders.outcomes(order_id) == []  # nothing happened; order_service isn't told
    assert customer.pay(order_id, "mock_tok_unavailable", key="unavail-key-1").status_code == 503
    assert customer.pay(order_id, key="unavail-key-2").status_code == 201


# --- Reporting and compensation -----------------------------------------------------------------------


def test_failed_report_is_retried_by_the_background_job(ctx):
    customer = ctx.customer()
    order_id = ctx.orders.add_order(customer.id)
    ctx.orders.fail("result", "timeout")
    response = customer.pay(order_id)
    assert response.status_code == 201 and response.json()["status"] == "SUCCEEDED"
    row = ctx.payment_row(response.json()["payment_id"])
    assert row.result_reported_at is None and row.report_attempts == 1
    assert ctx.background()["reported"] == 1
    assert ctx.orders.orders[order_id]["status"] == "PAID"


def test_payment_the_order_cannot_accept_is_refunded_automatically(ctx):
    customer = ctx.customer()
    order_id = ctx.orders.add_order(customer.id)
    # The reservation expires between the payable check and the payment result.
    ctx.orders.before_result = lambda oid: ctx.orders.orders[oid].update(status="CANCELLED")
    response = customer.pay(order_id, key="late-key-001")
    assert response.status_code == 409 and code(response) == "ORDER_NOT_FULFILLABLE"
    [summary] = customer.get("/api/payments", params={"order_id": order_id}).json()["items"]
    detail = customer.get(f"/api/payments/{summary['payment_id']}").json()
    assert detail["status"] == "REFUNDED"
    assert [r["status"] for r in detail["refunds"]] == ["SUCCEEDED"]
    assert detail["refunds"][0]["provider_reference"].startswith("mock_rfnd_")
    assert ctx.orders.outcomes(order_id) == ["SUCCEEDED", "REFUNDED"]
    assert customer.pay(order_id, key="late-key-001").status_code == 409  # replay: same answer


def test_admin_refunds(ctx):
    customer, admin = ctx.customer(), ctx.customer(role="admin")
    order_id = ctx.orders.add_order(customer.id, amount="100.00")
    payment_id = customer.pay(order_id).json()["payment_id"]
    path = f"/api/payments/{payment_id}/refunds"
    refund = lambda key, **body: ctx.client.post(path, headers={**admin.headers, "Idempotency-Key": key}, json=body)  # noqa: E731

    partial = refund("refund-key-1", amount="30.00", reason="damaged item")
    assert partial.status_code == 201 and partial.json()["amount"] == "30.00"
    assert refund("refund-key-1", amount="30.00").json()["refund_id"] == partial.json()["refund_id"]  # idempotent
    too_much = refund("refund-key-2", amount="80.00")
    assert too_much.status_code == 409 and code(too_much) == "PAYMENT_NOT_REFUNDABLE"
    rest = refund("refund-key-3")
    assert rest.json()["amount"] == "70.00"
    detail = admin.get(f"/api/payments/{payment_id}").json()
    assert detail["status"] == "REFUNDED" and len(detail["refunds"]) == 2
    assert ctx.orders.outcomes(order_id)[-1] == "REFUNDED"
    assert code(refund("refund-key-4")) == "PAYMENT_NOT_REFUNDABLE"


def test_mock_provider_is_refused_in_production():
    with pytest.raises(RuntimeError, match="development and tests only"):
        create_app(Settings(_env_file=None, APP_ENV="production", JWT_ISSUER="x"))


def test_webhooks_are_not_supported_by_the_mock(ctx):
    response = ctx.client.post("/api/payments/webhooks/mock", json={})
    assert response.status_code == 501 and code(response) == "WEBHOOKS_NOT_SUPPORTED"
