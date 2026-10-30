"""Product, category, inventory and reservation API tests (SQLite; concurrency runs on MySQL)."""

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import Database
from app.main import create_app
from app.models import Base, Inventory, InventoryMovement, Product, StockReservation
from app.models.base import utcnow
from app.stock import expire_due
from tests.jwt_helpers import bearer, make_token, KEY_PROVIDER

ADMIN_ID = uuid.uuid4()
ADMIN = bearer(make_token(ADMIN_ID, role="admin"))
CUSTOMER = bearer(make_token(role="customer"))
ORDER_SVC = bearer(make_token("svc:order", token_use="service", scope="products:read inventory:reserve"))
SHOE = {"sku": "shoe-trail-01", "name": "Trail Running Shoe", "price": "2499.00", "initial_stock": 10}


class Api:
    def __init__(self, client: TestClient, db: Database):
        self.client, self.db = client, db

    def product(self, **overrides) -> dict:
        response = self.client.post("/api/products", headers=ADMIN, json={**SHOE, **overrides})
        assert response.status_code == 201, response.text
        return response.json()

    def category(self, name: str, parent_id: str | None = None) -> dict:
        response = self.client.post("/api/categories", headers=ADMIN, json={"name": name, "parent_id": parent_id})
        assert response.status_code == 201, response.text
        return response.json()

    def reserve(self, order_id, items, **extra):
        return self.client.post(
            "/internal/reservations",
            headers=ORDER_SVC,
            json={"order_id": str(order_id), "items": [{"product_id": p, "quantity": q} for p, q in items], **extra},
        )

    def levels(self, product_id: str) -> tuple[int, int]:
        with self.db.session() as session:
            inv = session.get(Inventory, uuid.UUID(product_id))
            return inv.quantity_on_hand, inv.quantity_reserved

    def assert_ledger_consistent(self) -> None:
        """No negative stock, and the audit log adds up to the stored levels for every product."""
        with self.db.session() as session:
            for inv in session.scalars(select(Inventory)).all():
                assert 0 <= inv.quantity_reserved <= inv.quantity_on_hand
                on_hand, reserved = session.execute(
                    select(
                        func.coalesce(func.sum(InventoryMovement.quantity_change), 0),
                        func.coalesce(func.sum(InventoryMovement.reserved_change), 0),
                    ).where(InventoryMovement.product_id == inv.product_id)
                ).one()
                assert (on_hand, reserved) == (inv.quantity_on_hand, inv.quantity_reserved)


@pytest.fixture
def api():
    app = create_app(
        Settings(_env_file=None, APP_ENV="test", RESERVATION_SWEEP_SECONDS=0), key_provider=KEY_PROVIDER
    )
    db = Database("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(db.engine)
    app.state.db = db
    with TestClient(app, raise_server_exceptions=False) as client:
        yield Api(client, db)
    db.dispose()


def error_code(response) -> str:
    return response.json()["error"]["code"]


# --- Products ----------------------------------------------------------------------------


def test_create_and_read_a_product(api):
    category = api.category("Running Shoes")
    created = api.product(category_id=category["category_id"], description="Grippy outsole.")
    assert created["sku"] == "SHOE-TRAIL-01"  # normalised
    assert created["price"] == "2499.00" and created["currency"] == "INR"
    assert created["available_quantity"] == 10 and created["status"] == "ACTIVE"
    assert created["category"] == {"category_id": category["category_id"], "name": "Running Shoes"}

    fetched = api.client.get(f"/api/products/{created['product_id']}")  # public, no token
    assert fetched.status_code == 200 and fetched.json() == created
    missing = api.client.get(f"/api/products/{uuid.uuid4()}")
    assert missing.status_code == 404 and error_code(missing) == "PRODUCT_NOT_FOUND"
    api.assert_ledger_consistent()


@pytest.mark.parametrize(
    "overrides,field",
    [
        ({"price": "0"}, "price"),
        ({"price": "-5.00"}, "price"),
        ({"price": "10.999"}, "price"),
        ({"price": "99999999999.00"}, "price"),
        ({"name": "   "}, "name"),
        ({"name": "Bad\x00name"}, "name"),
        ({"name": "x" * 201}, "name"),
        ({"description": "x" * 5001}, "description"),
        ({"sku": "has space"}, "sku"),
        ({"sku": "-leading-dash"}, "sku"),
        ({"currency": "inr"}, "currency"),
        ({"initial_stock": -1}, "initial_stock"),
        ({"initial_stock": 1_000_001}, "initial_stock"),
        ({"unexpected": True}, "unexpected"),
    ],
)
def test_invalid_product_input_is_rejected(api, overrides, field):
    response = api.client.post("/api/products", headers=ADMIN, json={**SHOE, **overrides})
    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"
    assert any(field in d["field"] for d in response.json()["error"]["details"])


def test_duplicate_sku_is_a_conflict_regardless_of_case(api):
    api.product()
    response = api.client.post("/api/products", headers=ADMIN, json={**SHOE, "sku": "SHOE-TRAIL-01", "name": "Other"})
    assert response.status_code == 409 and error_code(response) == "DUPLICATE_SKU"


def test_unknown_category_reference_is_rejected(api):
    response = api.client.post("/api/products", headers=ADMIN, json={**SHOE, "category_id": str(uuid.uuid4())})
    assert response.status_code == 422 and error_code(response) == "CATEGORY_NOT_FOUND"


def test_update_product(api):
    product = api.product()
    path = f"/api/products/{product['product_id']}"
    updated = api.client.patch(path, headers=ADMIN, json={"price": "1999.50", "name": "Trail Shoe v2"})
    assert updated.status_code == 200
    assert updated.json()["price"] == "1999.50" and updated.json()["name"] == "Trail Shoe v2"
    for body in ({"name": None}, {"price": None}, {"sku": "NEW-SKU"}, {"category_id": str(uuid.uuid4())}):
        assert api.client.patch(path, headers=ADMIN, json=body).status_code == 422


def test_archived_products_are_hidden_from_customers(api):
    product = api.product()
    path = f"/api/products/{product['product_id']}"
    assert api.client.delete(path, headers=ADMIN).status_code == 204
    assert api.client.get(path).status_code == 404
    assert api.client.get("/api/products").json()["total"] == 0
    assert api.client.get(path, headers=ADMIN).json()["status"] == "ARCHIVED"
    admin_list = api.client.get("/api/products", params={"status": "ARCHIVED"}, headers=ADMIN).json()
    assert admin_list["total"] == 1
    assert api.client.get("/api/products", params={"status": "ARCHIVED"}, headers=CUSTOMER).status_code == 403
    # Reactivate.
    assert api.client.patch(path, headers=ADMIN, json={"status": "ACTIVE"}).json()["status"] == "ACTIVE"


def test_listing_pagination_filtering_search_and_sorting(api):
    shoes, socks = api.category("Shoes"), api.category("Socks")
    api.product(sku="SHOE-1", name="Trail Shoe", price="2499.00", category_id=shoes["category_id"])
    api.product(sku="SHOE-2", name="Road Shoe", price="1999.00", category_id=shoes["category_id"], initial_stock=0)
    api.product(sku="SOCK-1", name="Running Socks 3-Pack", price="299.00", category_id=socks["category_id"],
                description="Breathable 100% cotton")

    def names(**params):
        body = api.client.get("/api/products", params=params).json()
        return [item["name"] for item in body["items"]], body["total"]

    assert names(sort="price") == (["Running Socks 3-Pack", "Road Shoe", "Trail Shoe"], 3)
    assert names(sort="-price", limit=1, offset=1) == (["Road Shoe"], 3)
    assert names(q="shoe", sort="name") == (["Road Shoe", "Trail Shoe"], 2)
    assert names(q="sock-1") == (["Running Socks 3-Pack"], 1)  # SKU search
    assert names(q="100%") == (["Running Socks 3-Pack"], 1)  # % is literal, not a wildcard
    assert names(q="%") == (["Running Socks 3-Pack"], 1)
    assert names(category_id=shoes["category_id"], sort="name")[1] == 2
    assert names(min_price="300", max_price="2000") == (["Road Shoe"], 1)
    assert names(in_stock="true", sort="name") == (["Running Socks 3-Pack", "Trail Shoe"], 2)
    assert names(in_stock="false") == (["Road Shoe"], 1)
    in_stock_flags = {i["name"]: i["in_stock"] for i in api.client.get("/api/products").json()["items"]}
    assert in_stock_flags["Road Shoe"] is False

    for params in ({"limit": 500}, {"limit": 0}, {"offset": -1}, {"sort": "sku"}, {"min_price": "5", "max_price": "1"}):
        response = api.client.get("/api/products", params=params)
        assert response.status_code == 422 and error_code(response) == "VALIDATION_ERROR"


# --- Authorization -------------------------------------------------------------------------


def test_only_admins_can_change_catalog_prices_or_stock(api):
    product = api.product()
    pid = product["product_id"]
    attempts = [
        ("post", "/api/products", {**SHOE, "sku": "NEW-1"}),
        ("patch", f"/api/products/{pid}", {"price": "1.00"}),
        ("delete", f"/api/products/{pid}", None),
        ("patch", f"/api/products/{pid}/inventory", {"quantity_change": 100, "reason": "RESTOCK"}),
        ("get", f"/api/products/{pid}/inventory", None),
        ("post", "/api/categories", {"name": "Hacked"}),
    ]
    for method, path, body in attempts:
        kwargs = {"json": body} if body is not None else {}
        assert api.client.request(method, path, **kwargs).status_code == 401, path
        customer = api.client.request(method, path, headers=CUSTOMER, **kwargs)
        assert customer.status_code == 403 and error_code(customer) == "FORBIDDEN", path
        assert api.client.request(method, path, headers=ORDER_SVC, **kwargs).status_code == 401, path

    after = api.client.get(f"/api/products/{pid}").json()
    assert after["price"] == "2499.00" and after["available_quantity"] == 10 and after["status"] == "ACTIVE"


def test_a_bad_token_on_a_public_route_is_rejected_not_ignored(api):
    response = api.client.get("/api/products", headers=bearer("garbage"))
    assert response.status_code == 401 and error_code(response) == "INVALID_TOKEN"


# --- Categories ----------------------------------------------------------------------------


def test_category_management(api):
    parent = api.category("Footwear")
    child = api.category("Running Shoes", parent["category_id"])
    listing = api.client.get("/api/categories").json()
    assert listing["total"] == 2 and [c["name"] for c in listing["items"]] == ["Footwear", "Running Shoes"]
    assert api.client.get("/api/categories", params={"parent_id": parent["category_id"]}).json()["total"] == 1
    assert api.client.get(f"/api/categories/{child['category_id']}").json()["parent_id"] == parent["category_id"]

    dup = api.client.post("/api/categories", headers=ADMIN, json={"name": "Footwear"})
    assert dup.status_code == 409 and error_code(dup) == "DUPLICATE_CATEGORY"
    bad_parent = api.client.post("/api/categories", headers=ADMIN, json={"name": "X", "parent_id": str(uuid.uuid4())})
    assert bad_parent.status_code == 422
    cycle = api.client.patch(f"/api/categories/{parent['category_id']}", headers=ADMIN,
                             json={"parent_id": child["category_id"]})
    assert cycle.status_code == 422 and error_code(cycle) == "INVALID_CATEGORY_PARENT"
    renamed = api.client.patch(f"/api/categories/{child['category_id']}", headers=ADMIN, json={"name": "Trail"})
    assert renamed.json()["name"] == "Trail"

    api.product(category_id=child["category_id"])
    in_use = api.client.delete(f"/api/categories/{child['category_id']}", headers=ADMIN)
    assert in_use.status_code == 409 and error_code(in_use) == "CATEGORY_IN_USE"
    assert api.client.delete(f"/api/categories/{parent['category_id']}", headers=ADMIN).status_code == 409
    missing = api.client.get(f"/api/categories/{uuid.uuid4()}")
    assert missing.status_code == 404 and error_code(missing) == "CATEGORY_NOT_FOUND"


# --- Admin stock adjustments and audit --------------------------------------------------------


def test_stock_adjustments_are_audited_and_never_go_below_reserved(api):
    pid = api.product()["product_id"]
    path = f"/api/products/{pid}/inventory"
    restocked = api.client.patch(path, headers=ADMIN, json={"quantity_change": 5, "reason": "RESTOCK", "note": "PO-1"})
    assert restocked.status_code == 200 and restocked.json()["quantity_available"] == 15
    api.reserve(uuid.uuid4(), [(pid, 12)])

    too_much = api.client.patch(path, headers=ADMIN, json={"quantity_change": -4, "reason": "ADJUST"})
    assert too_much.status_code == 409 and error_code(too_much) == "INSUFFICIENT_STOCK"
    assert api.levels(pid) == (15, 12)
    assert api.client.patch(path, headers=ADMIN, json={"quantity_change": -3, "reason": "ADJUST"}).status_code == 200
    for body in ({"quantity_change": 0, "reason": "ADJUST"}, {"quantity_change": -1, "reason": "RESTOCK"},
                 {"quantity_change": 1, "reason": "CONFIRM"}):
        assert api.client.patch(path, headers=ADMIN, json=body).status_code == 422

    movements = api.client.get(f"{path}/movements", headers=ADMIN).json()
    assert [m["reason"] for m in movements["items"]] == ["ADJUST", "RESERVE", "RESTOCK", "RESTOCK"]
    adjust, reserve, restock = movements["items"][0], movements["items"][1], movements["items"][2]
    assert (adjust["quantity_change"], adjust["on_hand_after"], adjust["reserved_after"]) == (-3, 12, 12)
    assert adjust["actor"] == str(ADMIN_ID)
    assert reserve["actor"] == "svc:order" and reserve["reserved_change"] == 12
    assert restock["note"] == "PO-1"
    api.assert_ledger_consistent()


# --- Internal: availability and reservations -------------------------------------------------


def test_price_check_reports_prices_availability_and_missing_products(api):
    live = api.product()["product_id"]
    empty = api.product(sku="EMPTY", initial_stock=0)["product_id"]
    gone = api.product(sku="GONE")["product_id"]
    api.client.delete(f"/api/products/{gone}", headers=ADMIN)
    unknown = str(uuid.uuid4())
    body = {"product_ids": [live, empty, gone, unknown]}

    response = api.client.post("/internal/products/price-check", headers=ORDER_SVC, json=body)
    assert response.status_code == 200
    result = response.json()
    flags = {i["product_id"]: (i["orderable"], i["available_quantity"], i["price"]) for i in result["items"]}
    assert flags == {live: (True, 10, "2499.00"), empty: (False, 0, "2499.00"), gone: (False, 10, "2499.00")}
    assert result["missing"] == [unknown]

    assert api.client.post("/internal/products/price-check", headers=CUSTOMER, json=body).status_code == 401
    no_scope = bearer(make_token("svc:payment", token_use="service", scope="orders:read"))
    denied = api.client.post("/internal/products/price-check", headers=no_scope, json=body)
    assert denied.status_code == 403 and error_code(denied) == "INSUFFICIENT_SCOPE"


def test_reservation_is_all_or_nothing_and_replays_safely(api):
    a = api.product(sku="A", initial_stock=5)["product_id"]
    b = api.product(sku="B", initial_stock=1)["product_id"]
    order = uuid.uuid4()

    short = api.reserve(order, [(a, 2), (b, 2)])
    assert short.status_code == 409 and error_code(short) == "OUT_OF_STOCK"
    assert api.levels(a) == (5, 0) and api.levels(b) == (1, 0)  # nothing reserved

    created = api.reserve(order, [(a, 2), (b, 1)])
    assert created.status_code == 201
    assert created.json()["status"] == "RESERVED" and len(created.json()["items"]) == 2
    replay = api.reserve(order, [(b, 1), (a, 2)])
    assert replay.status_code == 200 and replay.json() == created.json()
    assert api.levels(a) == (5, 2) and api.levels(b) == (1, 1)  # held once, not twice

    different = api.reserve(order, [(a, 3)])
    assert different.status_code == 409 and error_code(different) == "RESERVATION_CONFLICT"
    sold_out = api.reserve(uuid.uuid4(), [(b, 1)])
    assert sold_out.status_code == 409 and error_code(sold_out) == "OUT_OF_STOCK"
    detail = api.client.get(f"/api/products/{b}").json()
    assert detail["available_quantity"] == 0
    api.assert_ledger_consistent()


def test_reservation_input_and_product_errors(api):
    pid = api.product()["product_id"]
    api.client.delete(f"/api/products/{api.product(sku='OLD')['product_id']}", headers=ADMIN)
    old = api.client.get("/api/products", params={"status": "ARCHIVED"}, headers=ADMIN).json()["items"][0]["product_id"]

    unknown = api.reserve(uuid.uuid4(), [(str(uuid.uuid4()), 1)])
    assert unknown.status_code == 404 and error_code(unknown) == "PRODUCT_NOT_FOUND"
    archived = api.reserve(uuid.uuid4(), [(old, 1)])
    assert archived.status_code == 409 and error_code(archived) == "PRODUCT_UNAVAILABLE"
    for items in ([(pid, 0)], [(pid, 1), (pid, 1)], []):
        assert api.reserve(uuid.uuid4(), items).status_code == 422
    customer = api.client.post("/internal/reservations", headers=CUSTOMER,
                               json={"order_id": str(uuid.uuid4()), "items": [{"product_id": pid, "quantity": 1}]})
    assert customer.status_code == 401
    assert api.levels(pid) == (10, 0)


def test_confirm_deducts_stock_once_and_release_returns_it(api):
    pid = api.product()["product_id"]
    paid, cancelled = uuid.uuid4(), uuid.uuid4()
    api.reserve(paid, [(pid, 3)])
    api.reserve(cancelled, [(pid, 4)])
    assert api.levels(pid) == (10, 7)

    confirm = api.client.post(f"/internal/reservations/{paid}/confirm", headers=ORDER_SVC)
    assert confirm.status_code == 200 and confirm.json()["status"] == "CONFIRMED"
    assert api.client.post(f"/internal/reservations/{paid}/confirm", headers=ORDER_SVC).status_code == 200
    assert api.levels(pid) == (7, 4)  # deducted once

    release = api.client.post(f"/internal/reservations/{cancelled}/release", headers=ORDER_SVC)
    assert release.json() == {"order_id": str(cancelled), "released_items": 1}
    assert api.client.post(f"/internal/reservations/{cancelled}/release", headers=ORDER_SVC).json()["released_items"] == 0
    assert api.levels(pid) == (7, 0)

    nothing = api.client.post(f"/internal/reservations/{uuid.uuid4()}/release", headers=ORDER_SVC)
    assert nothing.status_code == 200 and nothing.json()["released_items"] == 0
    after_confirm = api.client.post(f"/internal/reservations/{paid}/release", headers=ORDER_SVC)
    assert after_confirm.status_code == 409 and error_code(after_confirm) == "RESERVATION_ALREADY_CONFIRMED"
    after_release = api.client.post(f"/internal/reservations/{cancelled}/confirm", headers=ORDER_SVC)
    assert after_release.status_code == 409 and error_code(after_release) == "RESERVATION_EXPIRED"
    missing = api.client.post(f"/internal/reservations/{uuid.uuid4()}/confirm", headers=ORDER_SVC)
    assert missing.status_code == 404 and error_code(missing) == "RESERVATION_NOT_FOUND"
    api.assert_ledger_consistent()


def _expire(api: Api, order_id) -> None:
    with api.db.session() as session:
        session.execute(
            update(StockReservation)
            .where(StockReservation.order_id == order_id)
            .values(expires_at=utcnow() - timedelta(minutes=1))
        )
        session.commit()


def test_expired_reservations_return_stock(api):
    pid = api.product()["product_id"]
    late, abandoned = uuid.uuid4(), uuid.uuid4()
    assert api.reserve(late, [(pid, 2)], ttl_seconds=60).status_code == 201
    api.reserve(abandoned, [(pid, 5)])
    _expire(api, late)
    _expire(api, abandoned)

    confirm = api.client.post(f"/internal/reservations/{late}/confirm", headers=ORDER_SVC)
    assert confirm.status_code == 409 and error_code(confirm) == "RESERVATION_EXPIRED"
    assert api.levels(pid) == (10, 5)  # the late order's stock went back

    with api.db.session() as session:
        assert expire_due(session) == 1  # the background job's unit of work
    assert api.levels(pid) == (10, 0)
    assert api.client.post(f"/internal/reservations/{abandoned}/confirm", headers=ORDER_SVC).status_code == 409
    api.assert_ledger_consistent()


# --- Transaction rollback ---------------------------------------------------------------------------


def test_a_failure_mid_request_rolls_back_every_row_it_wrote(api, monkeypatch):
    from app import catalog

    def fail_after_flush(session, *args, **kwargs):
        session.flush()  # product and inventory rows are now written inside the transaction
        raise RuntimeError("simulated failure after writing; internal detail")

    monkeypatch.setattr(catalog, "record_movement", fail_after_flush)
    response = api.client.post("/api/products", headers=ADMIN, json=SHOE)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "simulated" not in response.text and "Traceback" not in response.text
    with api.db.session() as session:
        for model in (Product, Inventory, InventoryMovement):
            assert session.scalar(select(func.count()).select_from(model)) == 0, model.__name__


def test_a_rejected_duplicate_leaves_no_partial_rows(api):
    api.product()
    assert api.client.post("/api/products", headers=ADMIN, json={**SHOE, "name": "Copy"}).status_code == 409
    with api.db.session() as session:
        counts = [session.scalar(select(func.count()).select_from(m)) for m in (Product, Inventory, InventoryMovement)]
    assert counts == [1, 1, 1]
