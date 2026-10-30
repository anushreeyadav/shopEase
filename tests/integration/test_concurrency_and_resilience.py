"""Concurrency across services, and behaviour when a service stops or restarts."""

import threading
from concurrent.futures import ThreadPoolExecutor

from tests.integration.conftest import Shopper


def test_parallel_checkouts_never_oversell(gw, admin, make_product):
    product = make_product(stock=3)
    shoppers = [Shopper(gw) for _ in range(8)]
    for s in shoppers:
        s.address()
    barrier = threading.Barrier(len(shoppers))

    def checkout(s):
        barrier.wait()
        return s.order([(product, 1)]).status_code

    with ThreadPoolExecutor(len(shoppers)) as pool:
        statuses = list(pool.map(checkout, shoppers))
    assert statuses.count(201) == 3 and statuses.count(409) == 5, statuses
    inventory = gw.get(f"/api/products/{product}/inventory", headers=admin.headers).json()
    assert inventory["quantity_reserved"] == 3 and inventory["quantity_available"] == 0


def test_a_stopped_service_degrades_cleanly_and_recovers(gw, compose, shopper, make_product):
    product = make_product()
    shopper.address()
    assert compose.run("stop", "product_service").returncode == 0
    try:
        browse = gw.get("/api/products")
        assert browse.status_code == 503 and browse.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert "product_service:" not in browse.text
        order = shopper.order([(product, 1)])
        assert order.status_code in (503, 504)
        assert gw.get("/api/orders", headers=shopper.headers).json()["total"] == 0  # nothing stored
        ready = gw.get("/health/ready")
        assert ready.status_code == 503 and ready.json()["checks"]["product_service"] == "unavailable"
    finally:
        assert compose.run("start", "product_service").returncode == 0
    assert compose.healthy("product_service")
    assert shopper.order([(product, 1)]).status_code == 201


def test_restarting_a_service_keeps_the_system_working(gw, compose, shopper, make_product):
    product = make_product()
    assert compose.run("restart", "order_service").returncode == 0
    assert compose.healthy("order_service")
    order_id = shopper.order([(product, 1)]).json()["order_id"]
    assert shopper.pay(order_id).status_code == 201
