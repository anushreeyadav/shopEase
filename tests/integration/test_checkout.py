"""Full checkout across all services, with the MOCK payment provider."""

import uuid

from tests.integration.conftest import wait_until


def test_full_checkout_with_mock_payment(gw, shopper, admin, make_product):
    product = make_product(stock=5, price="2499.00")
    order = shopper.order([(product, 2)])
    assert order.status_code == 201, order.text
    body = order.json()
    assert body["status"] == "AWAITING_PAYMENT" and body["total_amount"] == "4998.00"
    assert {"order_id", "items", "total_amount", "currency", "status_history", "payment_due_by"} <= set(body)
    assert gw.get(f"/api/products/{product}").json()["available_quantity"] == 3  # reserved

    payment = shopper.pay(body["order_id"])
    assert payment.status_code == 201, payment.text
    assert payment.json()["status"] == "SUCCEEDED" and payment.json()["provider_reference"].startswith("mock_")

    detail = gw.get(f"/api/orders/{body['order_id']}", headers=shopper.headers).json()
    assert detail["status"] == "PAID" and detail["payment_status"] == "SUCCEEDED"
    assert [h["to_status"] for h in detail["status_history"]] == ["PENDING", "AWAITING_PAYMENT", "PAID"]
    inventory = gw.get(f"/api/products/{product}/inventory", headers=admin.headers).json()
    assert (inventory["quantity_on_hand"], inventory["quantity_reserved"]) == (3, 0)

    history = gw.get("/api/orders", headers=shopper.headers).json()
    assert [o["order_id"] for o in history["items"]] == [body["order_id"]]
    payments = gw.get("/api/payments", params={"order_id": body["order_id"]}, headers=shopper.headers).json()
    assert payments["total"] == 1 and payments["items"][0]["status"] == "SUCCEEDED"


def test_out_of_stock_is_rejected_through_the_whole_chain(gw, shopper, make_product):
    product = make_product(stock=1)
    response = shopper.order([(product, 2)])
    assert response.status_code == 409 and response.json()["error"]["code"] == "OUT_OF_STOCK"
    assert gw.get("/api/orders", headers=shopper.headers).json()["total"] == 0


def test_decline_then_successful_retry(gw, shopper, make_product):
    order_id = shopper.order([(make_product(), 1)]).json()["order_id"]
    declined = shopper.pay(order_id, "mock_tok_decline")
    assert declined.status_code == 422 and declined.json()["error"]["code"] == "PAYMENT_DECLINED"
    assert gw.get(f"/api/orders/{order_id}", headers=shopper.headers).json()["status"] == "AWAITING_PAYMENT"
    assert shopper.pay(order_id).status_code == 201
    assert gw.get(f"/api/orders/{order_id}", headers=shopper.headers).json()["status"] == "PAID"


def test_repeated_submissions_create_one_order_and_one_charge(gw, shopper, make_product):
    product = make_product(stock=5)
    key = str(uuid.uuid4())
    first, again = shopper.order([(product, 1)], key=key), shopper.order([(product, 1)], key=key)
    assert first.status_code == again.status_code == 201
    assert first.json()["order_id"] == again.json()["order_id"]
    assert gw.get(f"/api/products/{product}").json()["available_quantity"] == 4

    pay_key = str(uuid.uuid4())
    p1, p2 = shopper.pay(first.json()["order_id"], key=pay_key), shopper.pay(first.json()["order_id"], key=pay_key)
    assert p1.json()["payment_id"] == p2.json()["payment_id"]
    listing = gw.get("/api/payments", params={"order_id": first.json()["order_id"]}, headers=shopper.headers).json()
    assert listing["total"] == 1


def test_uncertain_payment_is_reconciled_not_recharged(gw, shopper, make_product):
    order_id = shopper.order([(make_product(), 1)]).json()["order_id"]
    pending = shopper.pay(order_id, "mock_tok_timeout")
    assert pending.status_code == 202 and pending.json()["status"] == "PROCESSING"
    payment_id = pending.json()["payment_id"]
    blocked = shopper.pay(order_id, "mock_tok_success")
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "PAYMENT_ALREADY_IN_PROGRESS"

    # The runner sets a 1-second reconciliation schedule for this disposable stack.
    assert wait_until(lambda: gw.get(f"/api/payments/{payment_id}", headers=shopper.headers).json()["status"]
                      == "SUCCEEDED", timeout=40)
    assert wait_until(lambda: gw.get(f"/api/orders/{order_id}", headers=shopper.headers).json()["status"] == "PAID",
                      timeout=20)
    history = gw.get(f"/api/payments/{payment_id}", headers=shopper.headers).json()["status_history"]
    assert [h["source"] for h in history][-1] == "RECONCILIATION"


def test_cancellation_returns_stock_and_a_late_payment_is_refused(gw, shopper, make_product):
    product = make_product(stock=3)
    order_id = shopper.order([(product, 2)]).json()["order_id"]
    cancelled = gw.post(f"/api/orders/{order_id}/cancel", headers=shopper.headers)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"
    assert gw.get(f"/api/products/{product}").json()["available_quantity"] == 3
    late = shopper.pay(order_id)
    assert late.status_code == 409 and late.json()["error"]["code"] == "ORDER_NOT_PAYABLE"


def test_admin_refund_cancels_the_paid_order(gw, shopper, admin, make_product):
    order_id = shopper.order([(make_product(), 1)]).json()["order_id"]
    payment_id = shopper.pay(order_id).json()["payment_id"]
    refund = gw.post(f"/api/payments/{payment_id}/refunds",
                     headers={**admin.headers, "Idempotency-Key": str(uuid.uuid4())}, json={"reason": "integration test"})
    assert refund.status_code == 201 and refund.json()["status"] == "SUCCEEDED"
    assert gw.get(f"/api/payments/{payment_id}", headers=shopper.headers).json()["status"] == "REFUNDED"
    assert wait_until(lambda: gw.get(f"/api/orders/{order_id}", headers=shopper.headers).json()["status"]
                      == "CANCELLED", timeout=20)
