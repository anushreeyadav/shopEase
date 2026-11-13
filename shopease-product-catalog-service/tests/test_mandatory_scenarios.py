"""The 20 mandatory test scenarios (Task 11), one test each, plus the cross-cutting checks.

Every request goes through the real application with real Authorization headers: tokens are
verified by the stand-in Authentication Service of test_auth_integration.py, which applies the
same rules as shopease-auth-service. After each scenario the database rows are checked directly,
not only the HTTP response.

Scenario 20 (simultaneous stock updates) needs MySQL row locks and real commits; it runs with
CATALOG_SERVICE_TEST_DB=mysql and is skipped on SQLite.
"""

from decimal import Decimal

import pytest
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.models import Category, InventoryTransaction, Product, TransactionType
from app.services import inventory_service
from tests.test_auth_integration import (  # noqa: F401  (fixtures)
    ADMIN_ID,
    admin,
    auth_service,
    bearer,
    customer,
    http,
)

MISSING_ID = 999_999


@pytest.fixture
def category(http, admin) -> dict:
    response = http.post("/api/categories/", headers=admin, json={"name": "Phones", "description": "Mobiles"})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def new_product(http, admin, category):
    counter = iter(range(1, 1000))

    def _create(**fields) -> dict:
        body = {"category_id": category["id"], "name": "Galaxy Mobile", "sku": f"MOB-{next(counter):03d}",
                "price": "1500.00", "initial_stock": 10} | fields
        response = http.post("/api/products/", headers=admin, json=body)
        assert response.status_code == 201, response.text
        return response.json()

    return _create


def row(db, product_id: int) -> Product:
    db.expire_all()
    return db.get(Product, product_id)


def history(db, product_id: int) -> list[InventoryTransaction]:
    return list(db.scalars(select(InventoryTransaction).where(InventoryTransaction.product_id == product_id)
                           .order_by(InventoryTransaction.id)))


def assert_stock_matches_history(db, product_id: int) -> None:
    level = 0
    for movement in history(db, product_id):
        sign = 1 if movement.transaction_type == TransactionType.IN else -1
        assert movement.previous_stock == level
        assert movement.updated_stock == level + sign * movement.quantity >= 0
        level = movement.updated_stock
    assert row(db, product_id).stock_quantity == level


def errors(response) -> dict[str, str]:
    assert response.status_code == 422, response.text
    return {e["field"]: e["message"] for e in response.json()["errors"]}


# --- 1-4: create ---

def test_s01_create_product_with_valid_information(http, admin, category, db_session):
    response = http.post("/api/products/", headers=admin, json={
        "category_id": category["id"], "name": "Galaxy Mobile", "sku": "mob-100", "price": "1499.5",
        "discount_price": "1299.00", "brand": "Galaxy", "initial_stock": 7})
    assert response.status_code == 201
    body = response.json()
    assert (body["sku"], body["price"], body["discount_price"], body["effective_price"]) == (
        "MOB-100", "1499.50", "1299.00", "1299.00")
    assert (body["stock_quantity"], body["in_stock"], body["is_active"]) == (7, True, True)
    product = row(db_session, body["id"])
    assert (product.sku, product.price, product.category_id) == ("MOB-100", Decimal("1499.50"), category["id"])
    assert product.category.name == "Phones"  # the foreign key resolves to the category
    [initial] = history(db_session, body["id"])
    assert (initial.transaction_type, initial.quantity, initial.previous_stock, initial.updated_stock,
            initial.remarks) == (TransactionType.IN, 7, 0, 7, "Initial stock")


def test_s02_create_product_with_duplicate_sku(http, admin, category, new_product, db_session):
    new_product(sku="MOB-200")
    for sku in ("MOB-200", "mob-200"):
        response = http.post("/api/products/", headers=admin, json={
            "category_id": category["id"], "name": "Copy", "sku": sku, "price": "1.00"})
        assert (response.status_code, response.json()) == (409, {"detail": "A product with this SKU already exists"})
    assert db_session.scalar(select(func.count()).select_from(Product).where(Product.sku == "MOB-200")) == 1


def test_s03_create_product_with_invalid_category(http, admin, db_session):
    archived = http.post("/api/categories/", headers=admin, json={"name": "Archive"}).json()
    http.patch(f"/api/categories/{archived['id']}", headers=admin, json={"is_active": False})
    for category_id, message in ((MISSING_ID, "category_id does not refer to an existing category"),
                                 (archived["id"], "category_id refers to an inactive category"),
                                 (0, "Input should be greater than or equal to 1"),
                                 ("abc", "Input should be a valid integer, unable to parse string as an integer")):
        response = http.post("/api/products/", headers=admin, json={
            "category_id": category_id, "name": "Orphan", "sku": "ORPHAN-1", "price": "1.00"})
        assert errors(response) == {"category_id": message}
    assert db_session.scalar(select(func.count()).select_from(Product)) == 0


@pytest.mark.parametrize("field, value", [("price", "-0.01"), ("price", "-1500"), ("discount_price", "-1.00")])
def test_s04_create_product_with_negative_price(http, admin, category, db_session, field, value):
    body = {"category_id": category["id"], "name": "Bad", "sku": "BAD-1", "price": "10.00"} | {field: value}
    response = http.post("/api/products/", headers=admin, json=body)
    assert errors(response) == {field: "Input should be greater than or equal to 0"}
    assert db_session.scalar(select(func.count()).select_from(Product)) == 0


# --- 5-9: read, update, delete ---

def test_s05_retrieve_all_active_products(http, admin, customer, new_product, category):
    visible = new_product(name="Galaxy Mobile")
    hidden = new_product(name="Retired Mobile")
    http.delete(f"/api/products/{hidden['id']}", headers=admin)
    closed = http.post("/api/categories/", headers=admin, json={"name": "Closed"}).json()
    in_closed = new_product(name="Closed Mobile", category_id=closed["id"])
    http.patch(f"/api/categories/{closed['id']}", headers=admin, json={"is_active": False})
    for headers in ({}, customer, admin):
        body = http.get("/api/products/", headers=headers).json()
        assert [p["id"] for p in body["items"]] == [visible["id"]]
        assert body["total"] == 1
    everything = http.get("/api/products/", headers=admin, params={"include_inactive": True}).json()
    assert {p["id"] for p in everything["items"]} == {visible["id"], hidden["id"], in_closed["id"]}


@pytest.mark.parametrize("product_id, status", [("abc", 422), ("0", 422), ("-5", 422), ("1.5", 422),
                                                (str(2**31), 422), (str(MISSING_ID), 404)])
def test_s06_retrieve_product_with_invalid_id(http, product_id, status):
    response = http.get(f"/api/products/{product_id}")
    assert response.status_code == status
    if status == 404:
        assert response.json() == {"detail": "Product not found"}
    else:
        assert response.json()["errors"][0]["field"] == "product_id"


def test_s07_update_a_product(http, admin, new_product, category, db_session):
    product = new_product()
    body = {"category_id": category["id"], "name": "Galaxy Mobile 2", "description": "New model",
            "sku": "MOB-NEW", "price": "1600.00", "discount_price": None, "image_url": None,
            "brand": "Galaxy", "is_active": True}
    response = http.put(f"/api/products/{product['id']}", headers=admin, json=body)
    assert response.status_code == 200
    stored = row(db_session, product["id"])
    assert (stored.name, stored.sku, stored.price, stored.description) == (
        "Galaxy Mobile 2", "MOB-NEW", Decimal("1600.00"), "New model")
    assert stored.stock_quantity == 10  # PUT never touches stock
    assert errors(http.put(f"/api/products/{product['id']}", headers=admin, json={"name": "Only"})).keys() >= {"sku", "price"}
    assert http.put(f"/api/products/{MISSING_ID}", headers=admin, json=body | {"sku": "X-1"}).status_code == 404


def test_s08_partially_update_a_product(http, admin, new_product, db_session):
    product = new_product(brand="Galaxy")
    response = http.patch(f"/api/products/{product['id']}", headers=admin, json={"price": "1450.00"})
    assert response.status_code == 200
    stored = row(db_session, product["id"])
    assert (stored.price, stored.name, stored.brand, stored.stock_quantity) == (
        Decimal("1450.00"), "Galaxy Mobile", "Galaxy", 10)
    assert errors(http.patch(f"/api/products/{product['id']}", headers=admin,
                             json={"stock_quantity": 99})) == {"stock_quantity": "Extra inputs are not permitted"}
    assert errors(http.patch(f"/api/products/{product['id']}", headers=admin,
                             json={"discount_price": "1450.00"})) == {"discount_price": "discount_price must be lower than price"}


def test_s09_delete_deactivates_a_product(http, admin, customer, new_product, db_session):
    product = new_product()
    http.post(f"/api/inventory/{product['id']}/stock-out", headers=admin, json={"quantity": 2})
    response = http.delete(f"/api/products/{product['id']}", headers=admin)
    assert (response.status_code, response.json()) == (200, {"message": "Product deactivated"})
    assert http.get(f"/api/products/{product['id']}", headers=customer).status_code == 404
    stored = row(db_session, product["id"])
    assert stored is not None and stored.is_active is False  # the row is kept
    assert len(history(db_session, product["id"])) == 2  # and so is its history
    assert http.delete(f"/api/products/{MISSING_ID}", headers=admin).status_code == 404


# --- 10: categories ---

def test_s10_create_duplicate_category(http, admin, category, db_session):
    for name in ("Phones", "PHONES", "  phones  "):
        response = http.post("/api/categories/", headers=admin, json={"name": name})
        assert (response.status_code, response.json()) == (409, {"detail": "A category with this name already exists"})
    assert db_session.scalar(select(func.count()).select_from(Category)) == 1


# --- 11-12: search, filters, paging, sorting ---

@pytest.fixture
def catalogue(http, admin, new_product, category):
    other = http.post("/api/categories/", headers=admin, json={"name": "Laptops"}).json()
    return {
        "cheap": new_product(name="Budget Phone", sku="PHN-1", price="800.00", initial_stock=12),
        "mobile": new_product(name="Galaxy Mobile", sku="MOB-1", price="1500.00", initial_stock=5),
        "empty": new_product(name="Pixel Mobile", sku="MOB-2", price="4500.00", initial_stock=0),
        "laptop": new_product(name="Ultrabook", sku="LAP-1", price="5000.00", initial_stock=7, category_id=other["id"]),
        "laptops": other, "phones": category,
    }


def test_s11_search_and_filter_products(http, catalogue):
    def skus(**params):
        response = http.get("/api/products/", params=params)
        assert response.status_code == 200
        return [p["sku"] for p in response.json()["items"]]

    assert skus(search="mobile") == ["MOB-1", "MOB-2"]
    assert skus(search="lap-") == ["LAP-1"]
    assert skus(category_id=catalogue["laptops"]["id"]) == ["LAP-1"]
    assert skus(min_price="1000", max_price="5000") == ["MOB-1", "MOB-2", "LAP-1"]
    assert skus(availability="out_of_stock") == ["MOB-2"]
    assert skus(search="mobile", availability="in_stock", category_id=catalogue["phones"]["id"]) == ["MOB-1"]
    assert errors(http.get("/api/products/", params={"min_price": "50", "max_price": "10"})) == {
        "max_price": "max_price must not be lower than min_price"}


def test_s12_pagination_and_sorting(http, catalogue):
    first = http.get("/api/products/", params={"page": 1, "page_size": 3, "sort_by": "price", "sort_order": "asc"}).json()
    assert [p["price"] for p in first["items"]] == ["800.00", "1500.00", "4500.00"]
    assert (first["total"], first["page"], first["page_size"], first["total_pages"]) == (4, 1, 3, 2)
    second = http.get("/api/products/", params={"page": 2, "page_size": 3, "sort_by": "price", "sort_order": "asc"}).json()
    assert [p["price"] for p in second["items"]] == ["5000.00"]
    desc = http.get("/api/products/", params={"sort_by": "price", "sort_order": "desc"}).json()
    assert [p["price"] for p in desc["items"]] == ["5000.00", "4500.00", "1500.00", "800.00"]
    for bad in ({"page": 0}, {"page": -1}, {"page_size": 0}, {"page_size": 101}, {"sort_by": "id"}, {"sort_order": "up"}):
        assert http.get("/api/products/", params=bad).status_code == 422


# --- 13-17: inventory ---

def test_s13_increase_product_stock(http, admin, new_product, db_session):
    product = new_product(initial_stock=10)
    response = http.post(f"/api/inventory/{product['id']}/stock-in", headers=admin,
                         json={"quantity": 5, "remarks": "Supplier delivery"})
    assert response.status_code == 201
    tx = response.json()["transaction"]
    assert (tx["transaction_type"], tx["quantity"], tx["previous_stock"], tx["updated_stock"]) == ("IN", 5, 10, 15)
    assert row(db_session, product["id"]).stock_quantity == 15
    assert history(db_session, product["id"])[-1].remarks == "Supplier delivery"
    assert_stock_matches_history(db_session, product["id"])


def test_s14_decrease_product_stock(http, admin, new_product, db_session):
    product = new_product(initial_stock=10)
    response = http.post(f"/api/inventory/{product['id']}/stock-out", headers=admin, json={"quantity": 4})
    assert response.status_code == 201
    tx = response.json()["transaction"]
    assert (tx["transaction_type"], tx["previous_stock"], tx["updated_stock"]) == ("OUT", 10, 6)
    assert row(db_session, product["id"]).stock_quantity == 6
    assert_stock_matches_history(db_session, product["id"])


def test_s15_reduce_stock_below_zero(http, admin, new_product, db_session):
    product = new_product(initial_stock=3)
    response = http.post(f"/api/inventory/{product['id']}/stock-out", headers=admin, json={"quantity": 4})
    assert (response.status_code, response.json()) == (409, {"detail": "Insufficient stock: 3 available, 4 requested"})
    assert row(db_session, product["id"]).stock_quantity == 3
    assert len(history(db_session, product["id"])) == 1
    for quantity in (0, -1):
        assert http.post(f"/api/inventory/{product['id']}/stock-out", headers=admin,
                         json={"quantity": quantity}).status_code == 422
    # The database refuses negative stock on its own too (CHECK constraint).
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(text("UPDATE products SET stock_quantity = -1 WHERE id = :id"), {"id": product["id"]})


def test_s16_inventory_transaction_history(http, admin, new_product, db_session):
    product = new_product(initial_stock=10)
    for action, quantity in (("stock-in", 5), ("stock-out", 3), ("stock-out", 12)):
        assert http.post(f"/api/inventory/{product['id']}/{action}", headers=admin,
                         json={"quantity": quantity}).status_code == 201
    body = http.get(f"/api/inventory/{product['id']}/history", headers=admin).json()
    assert body["total"] == 4
    assert [(t["transaction_type"], t["previous_stock"], t["updated_stock"]) for t in body["items"]] == [
        ("OUT", 12, 0), ("OUT", 15, 12), ("IN", 10, 15), ("IN", 0, 10)]
    assert {t["id"] for t in body["items"]} == {t.id for t in history(db_session, product["id"])}
    assert_stock_matches_history(db_session, product["id"])


def test_s17_retrieve_low_stock_products(http, admin, new_product):
    low = new_product(sku="LOW-1", initial_stock=5)  # threshold 5 in tests: included
    empty = new_product(sku="LOW-0", initial_stock=0)
    new_product(sku="OK-6", initial_stock=6)
    report = http.get("/api/inventory/low-stock", headers=admin).json()
    assert [(r["product_id"], r["stock_quantity"], r["is_low_stock"]) for r in report] == [
        (empty["id"], 0, True), (low["id"], 5, True)]


# --- 18-19: authorization ---

def test_s18_administrative_apis_as_customer(http, admin, customer, new_product, category, db_session):
    product = new_product()
    pid = product["id"]
    calls = [
        ("post", "/api/categories/", {"name": "Nope"}),
        ("patch", f"/api/categories/{category['id']}", {"name": "Nope"}),
        ("delete", f"/api/categories/{category['id']}", None),
        ("post", "/api/products/", {"category_id": category["id"], "name": "Nope", "sku": "NOPE", "price": "1.00"}),
        ("put", f"/api/products/{pid}", {"category_id": category["id"], "name": "Nope", "description": None,
                                         "sku": "NOPE", "price": "1.00", "discount_price": None,
                                         "image_url": None, "brand": None, "is_active": True}),
        ("patch", f"/api/products/{pid}", {"price": "0.01"}),
        ("delete", f"/api/products/{pid}", None),
        ("get", f"/api/inventory/{pid}", None),
        ("post", f"/api/inventory/{pid}/stock-in", {"quantity": 1}),
        ("post", f"/api/inventory/{pid}/stock-out", {"quantity": 1}),
        ("get", f"/api/inventory/{pid}/history", None),
        ("get", "/api/inventory/low-stock", None),
        ("get", "/api/products/", None, {"include_inactive": True}),
    ]
    for method, path, body, *params in calls:
        response = http.request(method, path, headers=customer, json=body, params=params[0] if params else None)
        assert (response.status_code, response.json()) == (403, {"detail": "Admin role required"}), (method, path)
    stored = row(db_session, pid)
    assert (stored.price, stored.stock_quantity, stored.is_active) == (Decimal("1500.00"), 10, True)
    assert http.get(f"/api/products/{pid}", headers=customer).status_code == 200  # customers can browse


def test_s19_protected_apis_without_token_and_with_invalid_token(http, auth_service, new_product, category):
    pid = new_product()["id"]
    forged = auth_service.issue(ADMIN_ID, "ADMIN", secret="not-the-auth-service-secret-0123456789")
    expired = auth_service.issue(ADMIN_ID, lifetime=-60)
    headers_cases = {
        "no token": {},
        "malformed": {"Authorization": "Bearer not-a-jwt"},
        "forged signature": bearer(forged),
        "expired": bearer(expired),
        "wrong scheme": {"Authorization": f"Basic {forged}"},
    }
    calls = [("post", "/api/products/", {"category_id": category["id"], "name": "X", "sku": "X-1", "price": "1.00"}),
             ("patch", f"/api/products/{pid}", {"price": "1.00"}),
             ("delete", f"/api/products/{pid}", None),
             ("post", f"/api/inventory/{pid}/stock-in", {"quantity": 1}),
             ("get", f"/api/inventory/{pid}/history", None),
             ("post", "/api/categories/", {"name": "X"})]
    for case, headers in headers_cases.items():
        for method, path, body in calls:
            response = http.request(method, path, headers=headers, json=body)
            assert response.status_code == 401, (case, method, path)
            assert response.json() == {"detail": "Could not validate credentials"}
            assert response.headers.get("www-authenticate") == "Bearer"


# --- 20: simultaneous stock updates ---

@pytest.mark.skipif(not __import__("tests.conftest", fromlist=["USE_MYSQL"]).USE_MYSQL,
                    reason="needs MySQL row locks (CATALOG_SERVICE_TEST_DB=mysql)")
def test_s20_simultaneous_stock_updates_stay_consistent():
    """Delegates to test_inventory_concurrency (same scenario through HTTP, real commits)."""
    import tests.test_inventory_concurrency as concurrency
    from app.database.connection import SessionLocal

    with SessionLocal() as db:
        product = Product(category=Category(name="Scenario 20"), name="Scenario 20", sku="SCENARIO-20",
                          price=Decimal("1.00"))
        db.add(product)
        db.flush()
        inventory_service.record_movement(db, product, TransactionType.IN, 5, "Initial stock")
        db.commit()
        product_id, category_id = product.id, product.category_id
    try:
        outcomes = concurrency.run_together(
            [lambda db: inventory_service.stock_out(db, product_id, 1)] * concurrency.WORKERS)
        assert outcomes.count("ok") == 5
        stock, rows = concurrency.stock_and_history(product_id)
        assert stock == 0 and len(rows) == 6
        concurrency.assert_one_chain(stock, rows)
    finally:
        with SessionLocal() as db:
            db.execute(delete(InventoryTransaction).where(InventoryTransaction.product_id == product_id))
            db.execute(delete(Product).where(Product.id == product_id))
            db.execute(delete(Category).where(Category.id == category_id))
            db.commit()


# --- Cross-cutting: foreign keys, uniqueness, constraints, rollback ---

def test_foreign_keys_are_enforced(http, admin, new_product, category, db_session):
    product = new_product()
    # Through the API: a category with products is not deleted.
    assert http.delete(f"/api/categories/{category['id']}", headers=admin).status_code == 409
    # In the database: RESTRICT refuses deleting a referenced category or product, and an orphan row.
    for statement, params in (("DELETE FROM categories WHERE id = :id", {"id": category["id"]}),
                              ("DELETE FROM products WHERE id = :id", {"id": product["id"]}),
                              ("INSERT INTO inventory_transactions (product_id, transaction_type, quantity, "
                               "previous_stock, updated_stock, created_at) VALUES (:id, 'IN', 1, 0, 1, CURRENT_TIMESTAMP)",
                               {"id": MISSING_ID})):
        with pytest.raises((IntegrityError, OperationalError)), db_session.begin_nested():
            db_session.execute(text(statement), params)
    keys = {(fk["referred_table"], tuple(fk["constrained_columns"])) for table in ("products", "inventory_transactions")
            for fk in inspect(db_session.connection()).get_foreign_keys(table)}
    assert keys == {("categories", ("category_id",)), ("products", ("product_id",))}


def test_uniqueness_is_enforced_by_the_database(new_product, category, db_session):
    new_product(sku="UNIQ-1")
    for statement in ("INSERT INTO products (category_id, name, sku, price, stock_quantity, is_active, created_at, "
                      "updated_at) VALUES (:cid, 'Copy', 'UNIQ-1', 1, 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                      "INSERT INTO categories (name, is_active, created_at, updated_at) "
                      "VALUES ('Phones', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"):
        with pytest.raises(IntegrityError), db_session.begin_nested():
            db_session.execute(text(statement), {"cid": category["id"]})


def test_failed_stock_change_is_rolled_back(http, admin, new_product, db_session, db_engine):
    from sqlalchemy import event

    product = new_product(initial_stock=10)

    def fail_history_insert(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("INSERT INTO INVENTORY_TRANSACTIONS"):
            raise OperationalError("INSERT", {}, Exception("injected"))

    event.listen(db_engine, "before_cursor_execute", fail_history_insert)
    try:
        assert http.post(f"/api/inventory/{product['id']}/stock-out", headers=admin,
                         json={"quantity": 4}).status_code == 503
    finally:
        event.remove(db_engine, "before_cursor_execute", fail_history_insert)
    assert row(db_session, product["id"]).stock_quantity == 10
    assert len(history(db_session, product["id"])) == 1
    assert_stock_matches_history(db_session, product["id"])
