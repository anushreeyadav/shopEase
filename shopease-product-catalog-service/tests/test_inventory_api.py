"""Inventory endpoints: current stock, stock-in, stock-out, history and the low-stock report.

Every test that changes stock ends by checking consistency: the product's stock equals the
replayed history (each row starts where the previous one ended, the first at 0, the last at the
current stock). Concurrency is tested on MySQL in test_inventory_concurrency.py.
"""

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.config import get_settings
from app.models import InventoryTransaction, Product, TransactionType
from app.models.stock_guard import StockChangeWithoutTransaction
from app.services import inventory_service

MISSING_ID = 999_999
NOT_FOUND = {"detail": "Product not found"}
TRANSACTION_FIELDS = {"id", "product_id", "transaction_type", "quantity", "previous_stock", "updated_stock",
                      "remarks", "created_at"}


def url(product: dict, action: str = "") -> str:
    return f"/api/inventory/{product['id']}" + (f"/{action}" if action else "")


def full_history(client, product: dict) -> list[dict]:
    """Every transaction, oldest first, read through the API page by page."""
    rows, page = [], 1
    while True:
        body = client.get(url(product, "history"), params={"page": page, "page_size": 100}).json()
        rows += body["items"]
        if page >= body["total_pages"]:
            break
        page += 1
    assert len(rows) == body["total"]
    return rows[::-1]


def assert_consistent(client, product: dict) -> list[dict]:
    """Stock equals the replayed history, and every row's arithmetic is right."""
    history = full_history(client, product)
    stock = 0
    for row in history:
        assert row["previous_stock"] == stock, history
        sign = 1 if row["transaction_type"] == "IN" else -1
        assert row["updated_stock"] == stock + sign * row["quantity"] >= 0, history
        assert row["quantity"] > 0
        stock = row["updated_stock"]
    assert client.get(url(product)).json()["stock_quantity"] == stock
    assert client.get(f"/api/products/{product['id']}", params={"include_inactive": True}).json()["stock_quantity"] == stock
    return history


def history_rows(db_session, product_id: int) -> int:
    return db_session.scalar(select(func.count()).select_from(InventoryTransaction)
                             .where(InventoryTransaction.product_id == product_id))


# --- Current stock ---

def test_current_stock(client, make_product):
    product = make_product(initial_stock=10)
    assert client.get(url(product)).json() == {
        "product_id": product["id"], "sku": product["sku"], "name": product["name"],
        "stock_quantity": 10, "low_stock_threshold": 5, "is_low_stock": False,
    }


def test_current_stock_of_an_inactive_product(client, make_product):
    product = make_product(initial_stock=3)
    client.delete(f"/api/products/{product['id']}")
    assert client.get(url(product)).json()["stock_quantity"] == 3


# --- Initial stock ---

def test_initial_stock_is_the_first_in_transaction(client, make_product):
    product = make_product(initial_stock=7)
    [row] = assert_consistent(client, product)
    assert (row["transaction_type"], row["quantity"], row["previous_stock"], row["updated_stock"], row["remarks"]) == (
        "IN", 7, 0, 7, "Initial stock")


def test_no_initial_stock_means_no_transaction(client, make_product):
    product = make_product(initial_stock=0)
    assert full_history(client, product) == []
    assert client.get(url(product)).json()["stock_quantity"] == 0


def test_failed_create_records_no_initial_stock(client, make_product, db_session):
    make_product(sku="DUP-1", initial_stock=4)
    before = db_session.scalar(select(func.count()).select_from(InventoryTransaction))
    response = client.post("/api/products/", json={"sku": "DUP-1", "name": "Copy", "price": "1.00",
                                                   "category_id": make_product()["category_id"], "initial_stock": 9})
    assert response.status_code == 409
    assert db_session.scalar(select(func.count()).select_from(InventoryTransaction)) == before + 1  # make_product's own


def test_product_updates_never_change_stock(client, make_product):
    product = make_product(initial_stock=6)
    for method, body in (("patch", {"stock_quantity": 50}), ("patch", {"name": "Renamed"}),
                         ("put", {k: product[k] for k in ("category_id", "name", "description", "sku", "price",
                                                          "discount_price", "image_url", "brand", "is_active")})):
        response = getattr(client, method)(f"/api/products/{product['id']}", json=body)
        assert response.status_code in (200, 422)
    assert client.get(url(product)).json()["stock_quantity"] == 6
    assert len(assert_consistent(client, product)) == 1


# --- Stock-in ---

def test_stock_in(client, make_product):
    product = make_product(initial_stock=10)
    response = client.post(url(product, "stock-in"), json={"quantity": 5, "remarks": "  Supplier delivery  "})
    assert response.status_code == 201
    body = response.json()
    tx = body["transaction"]
    assert set(tx) == TRANSACTION_FIELDS
    assert (tx["product_id"], tx["transaction_type"], tx["quantity"], tx["previous_stock"], tx["updated_stock"]) == (
        product["id"], "IN", 5, 10, 15)
    assert tx["remarks"] == "Supplier delivery"
    assert tx["created_at"].endswith(("Z", "+00:00"))
    assert body["stock"]["stock_quantity"] == 15
    assert assert_consistent(client, product)[-1] == tx


def test_repeated_stock_in_accumulates(client, make_product):
    product = make_product(initial_stock=0)
    for quantity in (1, 2, 3, 4):
        client.post(url(product, "stock-in"), json={"quantity": quantity})
    assert client.get(url(product)).json()["stock_quantity"] == 10
    assert [row["updated_stock"] for row in assert_consistent(client, product)] == [1, 3, 6, 10]


def test_stock_in_above_the_maximum_changes_nothing(client, make_product):
    product = make_product(initial_stock=10)
    response = client.post(url(product, "stock-in"), json={"quantity": 1_000_000_000})
    assert response.status_code == 409
    assert response.json() == {"detail": "Stock would exceed the maximum allowed quantity"}
    assert len(assert_consistent(client, product)) == 1


def test_stock_in_for_an_inactive_product_is_allowed(client, make_product):
    product = make_product(initial_stock=0)
    client.delete(f"/api/products/{product['id']}")
    assert client.post(url(product, "stock-in"), json={"quantity": 2}).status_code == 201
    assert_consistent(client, product)


# --- Stock-out ---

def test_stock_out(client, make_product):
    product = make_product(initial_stock=10)
    response = client.post(url(product, "stock-out"), json={"quantity": 4, "remarks": "Order 1001"})
    assert response.status_code == 201
    tx = response.json()["transaction"]
    assert (tx["transaction_type"], tx["quantity"], tx["previous_stock"], tx["updated_stock"], tx["remarks"]) == (
        "OUT", 4, 10, 6, "Order 1001")
    assert response.json()["stock"]["stock_quantity"] == 6
    assert_consistent(client, product)


def test_stock_out_to_exactly_zero(client, make_product):
    product = make_product(initial_stock=10)
    tx = client.post(url(product, "stock-out"), json={"quantity": 10}).json()["transaction"]
    assert (tx["previous_stock"], tx["updated_stock"], tx["remarks"]) == (10, 0, None)
    assert client.get(f"/api/products/{product['id']}").json()["in_stock"] is False
    assert_consistent(client, product)


# --- Insufficient stock ---

@pytest.mark.parametrize("stock, requested", [(2, 3), (0, 1), (5, 1_000_000)])
def test_insufficient_stock_changes_nothing(client, db_session, make_product, stock, requested):
    product = make_product(initial_stock=stock)
    rows_before = history_rows(db_session, product["id"])
    response = client.post(url(product, "stock-out"), json={"quantity": requested})
    assert response.status_code == 409
    assert response.json() == {"detail": f"Insufficient stock: {stock} available, {requested} requested"}
    assert client.get(url(product)).json()["stock_quantity"] == stock
    assert history_rows(db_session, product["id"]) == rows_before
    assert_consistent(client, product)


def test_stock_out_after_a_refusal_still_works(client, make_product):
    product = make_product(initial_stock=3)
    assert client.post(url(product, "stock-out"), json={"quantity": 4}).status_code == 409
    assert client.post(url(product, "stock-out"), json={"quantity": 3}).status_code == 201
    assert len(assert_consistent(client, product)) == 2


# --- Zero, negative and other invalid quantities ---

@pytest.mark.parametrize("action", ["stock-in", "stock-out"])
@pytest.mark.parametrize("quantity, message", [
    (0, "Input should be greater than or equal to 1"),
    (-1, "Input should be greater than or equal to 1"),
    (-100, "Input should be greater than or equal to 1"),
    (1.5, "Input should be a valid integer"),
    (5.0, "Input should be a valid integer"),
    ("5", "Input should be a valid integer"),
    (True, "Input should be a valid integer"),
    (None, "Input should be a valid integer"),
    (10**12, "Input should be less than or equal to 1000000000"),
])
def test_invalid_quantities_are_422(client, make_product, action, quantity, message):
    product = make_product(initial_stock=10)
    response = client.post(url(product, action), json={"quantity": quantity})
    assert response.status_code == 422
    assert response.json() == {"detail": "Validation failed", "errors": [{"field": "quantity", "message": message}]}
    assert len(assert_consistent(client, product)) == 1


@pytest.mark.parametrize("body, field", [
    ({}, "quantity"),
    ({"quantity": 1, "remarks": "x" * 256}, "remarks"),
    ({"quantity": 1, "remarks": "line\nbreak"}, "remarks"),
    ({"quantity": 1, "remarks": "   "}, "remarks"),
    ({"quantity": 1, "transaction_type": "OUT"}, "transaction_type"),
    ({"quantity": 1, "previous_stock": 0}, "previous_stock"),
    ({"quantity": 1, "updated_stock": 99}, "updated_stock"),
])
def test_invalid_bodies_are_422(client, make_product, body, field):
    product = make_product()
    response = client.post(url(product, "stock-in"), json=body)
    assert response.status_code == 422
    assert field in {error["field"] for error in response.json()["errors"]}


def test_malformed_json_is_400(client, make_product):
    product = make_product()
    response = client.post(url(product, "stock-in"), content=b'{"quantity": ', headers={"Content-Type": "application/json"})
    assert response.status_code == 400


# --- Invalid and unknown product IDs ---

@pytest.mark.parametrize("method, action, body", [
    ("get", "", None), ("get", "history", None),
    ("post", "stock-in", {"quantity": 1}), ("post", "stock-out", {"quantity": 1}),
])
def test_unknown_product_is_404(client, method, action, body):
    path = f"/api/inventory/{MISSING_ID}" + (f"/{action}" if action else "")
    response = client.request(method, path, json=body)
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


@pytest.mark.parametrize("product_id", ["0", "-1", "abc", "1.5", str(2**31)])
def test_invalid_product_id_is_422(client, product_id):
    for path in (f"/api/inventory/{product_id}", f"/api/inventory/{product_id}/history"):
        response = client.get(path)
        assert response.status_code == 422
        assert response.json()["errors"][0]["field"] == "product_id"
    assert client.post(f"/api/inventory/{product_id}/stock-in", json={"quantity": 1}).status_code == 422


# --- Access ---

@pytest.mark.parametrize("method, action, body", [
    ("get", "", None), ("get", "history", None),
    ("post", "stock-in", {"quantity": 1}), ("post", "stock-out", {"quantity": 1}),
])
def test_admin_only(client, auth_as, make_product, method, action, body):
    product = make_product(initial_stock=5)
    path = url(product, action)
    auth_as(None)
    assert client.request(method, path, json=body).status_code == 401
    auth_as(7, role="USER")
    response = client.request(method, path, json=body)
    assert response.status_code == 403
    assert response.json() == {"detail": "Admin role required"}
    auth_as.admin()
    assert client.get(url(product)).json()["stock_quantity"] == 5


def test_low_stock_report_is_admin_only(client, auth_as):
    auth_as(None)
    assert client.get("/api/inventory/low-stock").status_code == 401
    auth_as(7, role="USER")
    assert client.get("/api/inventory/low-stock").status_code == 403


# --- History ---

def test_history_is_complete_newest_first(client, make_product):
    product = make_product(initial_stock=10)
    client.post(url(product, "stock-in"), json={"quantity": 5, "remarks": "Delivery"})
    client.post(url(product, "stock-out"), json={"quantity": 3})
    client.post(url(product, "stock-out"), json={"quantity": 2, "remarks": "Damaged"})

    body = client.get(url(product, "history")).json()
    assert body["total"] == 4
    assert all(set(row) == TRANSACTION_FIELDS for row in body["items"])
    steps = [(t["transaction_type"], t["quantity"], t["previous_stock"], t["updated_stock"], t["remarks"])
             for t in body["items"]]
    assert steps == [("OUT", 2, 12, 10, "Damaged"), ("OUT", 3, 15, 12, None), ("IN", 5, 10, 15, "Delivery"),
                     ("IN", 10, 0, 10, "Initial stock")]
    assert_consistent(client, product)


def test_history_pages_together_return_everything(client, make_product):
    product = make_product(initial_stock=1)
    for _ in range(24):
        client.post(url(product, "stock-in"), json={"quantity": 1})
    pages = [client.get(url(product, "history"), params={"page": n, "page_size": 10}).json() for n in (1, 2, 3)]
    assert [(p["total"], p["total_pages"], len(p["items"])) for p in pages] == [(25, 3, 10), (25, 3, 10), (25, 3, 5)]
    ids = [row["id"] for p in pages for row in p["items"]]
    assert len(set(ids)) == 25
    assert len(assert_consistent(client, product)) == 25


def test_history_filter_by_type(client, make_product):
    product = make_product(initial_stock=10)
    client.post(url(product, "stock-out"), json={"quantity": 1})
    client.post(url(product, "stock-out"), json={"quantity": 1})
    assert client.get(url(product, "history"), params={"transaction_type": "OUT"}).json()["total"] == 2
    assert client.get(url(product, "history"), params={"transaction_type": "IN"}).json()["total"] == 1


@pytest.mark.parametrize("params", [{"transaction_type": "MOVE"}, {"page": 0}, {"page_size": 101}, {"size": 5}])
def test_history_rejects_bad_query(client, make_product, params):
    product = make_product()
    assert client.get(url(product, "history"), params=params).status_code == 422


def test_history_is_per_product(client, make_product):
    first, second = make_product(initial_stock=1), make_product(initial_stock=2)
    client.post(url(first, "stock-in"), json={"quantity": 1})
    assert client.get(url(first, "history")).json()["total"] == 2
    assert client.get(url(second, "history")).json()["total"] == 1


def test_history_survives_deactivation(client, make_product):
    product = make_product(initial_stock=4)
    client.post(url(product, "stock-out"), json={"quantity": 1})
    client.delete(f"/api/products/{product['id']}")
    assert client.get(url(product, "history")).json()["total"] == 2


# --- Low stock ---

@pytest.fixture
def threshold(monkeypatch):
    """Sets LOW_STOCK_THRESHOLD for one test, the way the service reads it (environment + settings)."""
    def _set(value: int) -> None:
        monkeypatch.setenv("LOW_STOCK_THRESHOLD", str(value))
        get_settings.cache_clear()
    yield _set
    monkeypatch.undo()
    get_settings.cache_clear()


def test_low_stock_report(client, make_product):
    at_threshold = make_product(initial_stock=5)  # LOW_STOCK_THRESHOLD is 5 in tests
    empty = make_product(initial_stock=0)
    one_above = make_product(initial_stock=6)
    inactive = make_product(initial_stock=0)
    client.delete(f"/api/products/{inactive['id']}")

    report = client.get("/api/inventory/low-stock").json()
    assert [row["product_id"] for row in report] == [empty["id"], at_threshold["id"]]
    assert all(row["is_low_stock"] and row["low_stock_threshold"] == 5 for row in report)
    assert one_above["id"] not in {row["product_id"] for row in report}


def test_low_stock_threshold_comes_from_the_setting(client, make_product, threshold):
    products = {stock: make_product(initial_stock=stock) for stock in (0, 3, 10, 11)}
    threshold(10)
    report = client.get("/api/inventory/low-stock").json()
    assert [row["product_id"] for row in report] == [products[s]["id"] for s in (0, 3, 10)]
    assert {row["low_stock_threshold"] for row in report} == {10}
    assert client.get(url(products[11])).json()["is_low_stock"] is False
    threshold(0)
    assert [row["product_id"] for row in client.get("/api/inventory/low-stock").json()] == [products[0]["id"]]


def test_movements_move_products_in_and_out_of_the_report(client, make_product):
    product = make_product(initial_stock=6)
    assert product["id"] not in {r["product_id"] for r in client.get("/api/inventory/low-stock").json()}
    assert client.post(url(product, "stock-out"), json={"quantity": 1}).json()["stock"]["is_low_stock"] is True
    assert product["id"] in {r["product_id"] for r in client.get("/api/inventory/low-stock").json()}
    assert client.post(url(product, "stock-in"), json={"quantity": 1}).json()["stock"]["is_low_stock"] is False


def test_empty_low_stock_report(client, make_product):
    make_product(initial_stock=100)
    assert client.get("/api/inventory/low-stock").json() == []


# --- Failed transactions are rolled back ---

@pytest.fixture
def fail_statement(db_engine):
    """Makes the next SQL statement starting with the given text fail, as if the database refused it."""
    installed = []

    def _fail(prefix: str, error: Exception) -> None:
        def listener(_conn, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith(prefix):
                raise error
        event.listen(db_engine, "before_cursor_execute", listener)
        installed.append(listener)

    yield _fail
    for listener in installed:
        event.remove(db_engine, "before_cursor_execute", listener)


DB_DOWN = OperationalError("statement", {}, Exception("Lost connection to MySQL server"))
DB_REFUSED = IntegrityError("statement", {}, Exception("constraint failed"))


@pytest.mark.parametrize("failing, error, status, detail", [
    ("INSERT INTO INVENTORY_TRANSACTIONS", DB_DOWN, 503, "Service temporarily unavailable"),
    ("INSERT INTO INVENTORY_TRANSACTIONS", DB_REFUSED, 409,
     "The stock change was refused by the database; nothing was changed"),
    ("UPDATE PRODUCTS", DB_DOWN, 503, "Service temporarily unavailable"),
    ("UPDATE PRODUCTS", DB_REFUSED, 409, "The stock change was refused by the database; nothing was changed"),
])
@pytest.mark.parametrize("action", ["stock-in", "stock-out"])
def test_failure_of_either_write_rolls_back_both(client, make_product, fail_statement, failing, error, status,
                                                 detail, action):
    product = make_product(initial_stock=10)
    fail_statement(failing, error)
    response = client.post(url(product, action), json={"quantity": 3})
    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert "MySQL" not in response.text and "constraint" not in response.text


@pytest.mark.parametrize("error, status", [(DB_DOWN, 503), (DB_REFUSED, 409)])
@pytest.mark.parametrize("failing", ["INSERT INTO INVENTORY_TRANSACTIONS", "UPDATE PRODUCTS"])
def test_nothing_is_kept_after_a_failed_movement(client, db_session, make_product, db_engine, failing, error,
                                                 status):
    product = make_product(initial_stock=10)

    def listener(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith(failing):
            raise error

    event.listen(db_engine, "before_cursor_execute", listener)
    try:
        assert client.post(url(product, "stock-out"), json={"quantity": 3}).status_code == status
    finally:
        event.remove(db_engine, "before_cursor_execute", listener)
    db_session.expire_all()
    assert db_session.get(Product, product["id"]).stock_quantity == 10
    assert history_rows(db_session, product["id"]) == 1
    # The row lock was released: the next movement goes through.
    assert client.post(url(product, "stock-out"), json={"quantity": 3}).status_code == 201
    assert len(assert_consistent(client, product)) == 2


def test_failure_at_commit_keeps_nothing(client, db_session, make_product, monkeypatch):
    """Both writes reach the database, then the commit fails: neither may survive."""
    product = make_product(initial_stock=10)
    real_commit = db_session.commit

    def failing_commit():
        db_session.flush()  # the UPDATE and the INSERT have both been sent
        raise DB_DOWN

    monkeypatch.setattr(db_session, "commit", failing_commit)
    assert client.post(url(product, "stock-in"), json={"quantity": 5}).status_code == 503
    monkeypatch.setattr(db_session, "commit", real_commit)
    db_session.expire_all()
    assert db_session.get(Product, product["id"]).stock_quantity == 10
    assert history_rows(db_session, product["id"]) == 1
    assert_consistent(client, product)


# --- Stock never changes without a history row (app.models.stock_guard) ---

def test_direct_stock_change_is_refused(db_session, make_product):
    product = db_session.get(Product, make_product(initial_stock=5)["id"])
    product.stock_quantity = 50
    with pytest.raises(StockChangeWithoutTransaction):
        db_session.commit()
    db_session.rollback()
    db_session.expire_all()
    assert db_session.get(Product, product.id).stock_quantity == 5


def test_stock_change_with_a_wrong_history_row_is_refused(db_session, make_product):
    product = db_session.get(Product, make_product(initial_stock=5)["id"])
    product.stock_quantity = 8
    db_session.add(InventoryTransaction(product_id=product.id, transaction_type="IN", quantity=2,
                                        previous_stock=5, updated_stock=7))
    with pytest.raises(StockChangeWithoutTransaction):
        db_session.flush()
    db_session.rollback()


def test_new_product_cannot_start_with_stock(db_session, make_product):
    category_id = make_product()["category_id"]
    db_session.add(Product(category_id=category_id, name="Sneaky", sku="SNEAKY-1", price=1, stock_quantity=9))
    with pytest.raises(StockChangeWithoutTransaction):
        db_session.flush()
    db_session.rollback()


def test_recorded_movements_pass_the_guard(db_session, make_product):
    product = db_session.get(Product, make_product(initial_stock=5)["id"])
    inventory_service.record_movement(db_session, product, TransactionType.IN, 2, None)
    inventory_service.record_movement(db_session, product, TransactionType.OUT, 4, None)  # two movements in one flush
    db_session.flush()
    assert product.stock_quantity == 3
