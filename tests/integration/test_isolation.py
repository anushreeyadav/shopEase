"""Unauthorized access and cross-user data isolation, end to end through the gateway."""

import uuid

import pytest

from tests.integration.conftest import Shopper


@pytest.fixture
def two_shoppers(gw, make_product):
    owner, other = Shopper(gw), Shopper(gw)
    order_id = owner.order([(make_product(), 1)]).json()["order_id"]
    payment_id = owner.pay(order_id).json()["payment_id"]
    return owner, other, order_id, payment_id


def test_other_customers_see_nothing_of_mine(gw, two_shoppers):
    owner, other, order_id, payment_id = two_shoppers
    for path in (f"/api/orders/{order_id}", f"/api/payments/{payment_id}"):
        assert gw.get(path, headers=other.headers).status_code == 404
        assert gw.get(path, headers=owner.headers).status_code == 200
    assert gw.get("/api/orders", headers=other.headers).json()["total"] == 0
    assert gw.get("/api/payments", params={"order_id": order_id}, headers=other.headers).json()["total"] == 0
    assert gw.post(f"/api/orders/{order_id}/cancel", headers=other.headers).status_code == 404
    address = owner.address()
    assert gw.delete(f"/api/users/me/addresses/{address}", headers=other.headers).status_code == 404
    # Ordering with someone else's address fails too.
    foreign = gw.post("/api/orders", headers={**other.headers, "Idempotency-Key": str(uuid.uuid4())},
                      json={"items": [{"product_id": str(uuid.uuid4()), "quantity": 1}], "shipping_address_id": address})
    assert foreign.status_code in (404,)


def test_paying_someone_elses_order_is_refused(gw, two_shoppers, make_product):
    owner, other, _, _ = two_shoppers
    order_id = owner.order([(make_product(), 1)]).json()["order_id"]
    response = other.pay(order_id)
    assert response.status_code == 404 and response.json()["error"]["code"] == "ORDER_NOT_FOUND"


def test_customers_cannot_use_admin_operations(gw, shopper, make_product):
    product = make_product()
    for method, path, body in [
        ("POST", "/api/products", {"sku": "X-1", "name": "x", "price": "1.00"}),
        ("PATCH", f"/api/products/{product}", {"price": "1.00"}),
        ("PATCH", f"/api/products/{product}/inventory", {"quantity_change": 100, "reason": "RESTOCK"}),
        ("POST", "/api/categories", {"name": "Hacked"}),
        ("GET", f"/api/users/{uuid.uuid4()}", None),
    ]:
        response = gw.request(method, path, headers=shopper.headers, json=body)
        assert response.status_code == 403 and response.json()["error"]["code"] == "FORBIDDEN", (method, path)
    assert gw.get(f"/api/products/{product}").json()["price"] == "2499.00"


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/users/me"), ("GET", "/api/orders"), ("POST", "/api/orders"),
    ("GET", "/api/payments"), ("POST", "/api/payments"), ("POST", "/api/auth/logout"),
])
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not-a-token"},
                                     {"X-User-Id": str(uuid.uuid4()), "X-User-Token": "spoofed"}],
                         ids=["no-token", "garbage-token", "spoofed-headers"])
def test_protected_routes_reject_unauthenticated_callers(gw, method, path, headers):
    response = gw.request(method, path, headers=headers, json={})
    assert response.status_code == 401
    assert response.json()["error"]["code"] in ("UNAUTHENTICATED", "INVALID_TOKEN")


def test_logged_out_refresh_token_is_dead(gw, shopper):
    assert gw.post("/api/auth/logout", headers=shopper.headers,
                   json={"refresh_token": shopper.refresh_token}).status_code == 204
    assert gw.post("/api/auth/refresh", json={"refresh_token": shopper.refresh_token}).status_code == 401
