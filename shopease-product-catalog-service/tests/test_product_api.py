"""Product endpoints: POST/GET /api/products/, GET/PUT/PATCH/DELETE /api/products/{id}.

Search, filters, paging and sorting of GET /api/products/ are tested in test_product_search.py.

The caller is switched with auth_as: an admin by default, auth_as(None) for an anonymous
visitor, as_customer(auth_as) for a customer (the Authentication Service's role USER).
"""

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.inventory_model import InventoryTransaction
from app.models.product_model import Product
from app.services import product_service

PRODUCT_FIELDS = {
    "id", "category_id", "name", "description", "sku", "price", "discount_price", "effective_price",
    "stock_quantity", "in_stock", "image_url", "brand", "is_active", "created_at", "updated_at",
}
MISSING_ID = 12345
DUPLICATE_SKU = {"detail": "A product with this SKU already exists"}
NOT_FOUND = {"detail": "Product not found"}
DISCOUNT_MESSAGE = "discount_price must be lower than price"


def as_customer(auth_as) -> None:
    auth_as(7, role="USER")


def errors(response) -> dict[str, str]:
    """422 body as {field: message}."""
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["detail"] == "Validation failed"
    return {error["field"]: error["message"] for error in body["errors"]}


def product_count(db_session) -> int:
    return db_session.scalar(select(func.count()).select_from(Product))


@pytest.fixture
def new_product(category) -> dict:
    """A valid POST body."""
    return {"sku": "TEE-RED-M", "name": "Red Tee", "price": "19.99", "category_id": category["id"]}


def full_body(product: dict, **changes) -> dict:
    """A valid PUT body built from a product response."""
    fields = ("category_id", "name", "description", "sku", "price", "discount_price", "image_url", "brand", "is_active")
    return {field: product[field] for field in fields} | changes


# --- POST /api/products/ ---

def test_create_product(client, category):
    response = client.post("/api/products/", json={
        "sku": "tshirt-red-m", "name": "Red T-Shirt", "brand": "Basics", "price": "19.50",
        "discount_price": "15.00", "category_id": category["id"], "initial_stock": 12,
        "image_url": "https://cdn.example.com/p/1.png", "description": "Cotton",
    })
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == PRODUCT_FIELDS
    assert body["sku"] == "TSHIRT-RED-M"
    assert (body["price"], body["discount_price"], body["effective_price"]) == ("19.50", "15.00", "15.00")
    assert (body["stock_quantity"], body["in_stock"], body["brand"], body["is_active"]) == (12, True, "Basics", True)


def test_only_required_fields(client, new_product):
    body = client.post("/api/products/", json=new_product).json()
    assert (body["description"], body["discount_price"], body["image_url"], body["brand"]) == (None,) * 4
    assert (body["stock_quantity"], body["in_stock"], body["effective_price"]) == (0, False, "19.99")


@pytest.mark.parametrize("path", ["/api/products/", "/api/products"])
def test_collection_is_served_with_and_without_slash(client, new_product, path):
    assert client.post(path, json=new_product, follow_redirects=False).status_code == 201
    assert client.get(path, follow_redirects=False).status_code == 200


def test_required_fields_are_listed(client):
    assert errors(client.post("/api/products/", json={})) == {
        "category_id": "Field required", "name": "Field required", "sku": "Field required", "price": "Field required",
    }


def test_create_response_matches_stored_row(client, new_product):
    created = client.post("/api/products/", json=new_product | {"price": "19.5"}).json()
    assert created["price"] == "19.50"  # two places, as stored
    assert client.get(f"/api/products/{created['id']}").json() == created


# Names and other text

def test_name_and_brand_whitespace_is_normalised(client, new_product):
    body = client.post("/api/products/", json=new_product | {"name": "  Red    Tee ", "brand": " Big   Brand "}).json()
    assert (body["name"], body["brand"]) == ("Red Tee", "Big Brand")


@pytest.mark.parametrize(("changes", "field", "message"), [
    ({"name": ""}, "name", "String should have at least 1 character"),
    ({"name": "   "}, "name", "String should have at least 1 character"),
    ({"name": "***"}, "name", "must contain at least one letter or digit"),
    ({"name": "x" * 201}, "name", "String should have at most 200 characters"),
    ({"name": "Tee\nShirt"}, "name", "must not contain control characters"),
    ({"name": None}, "name", "Input should be a valid string"),
    ({"brand": "--"}, "brand", "must contain at least one letter or digit"),
    ({"description": "x" * 10_001}, "description", "String should have at most 10000 characters"),
    ({"image_url": "javascript:alert(1)"}, "image_url", "must be an http(s) URL"),
    ({"image_url": "https://user:pw@host/x.png"}, "image_url", "URL must not contain credentials"),
    ({"category_id": 0}, "category_id", "Input should be greater than or equal to 1"),
    ({"category_id": "abc"}, "category_id", "Input should be a valid integer, unable to parse string as an integer"),
])
def test_invalid_fields_get_clear_messages(client, new_product, changes, field, message):
    assert errors(client.post("/api/products/", json=new_product | changes)) == {field: message}


@pytest.mark.parametrize("sku", ["", "-ABC", "AB C", "AB_C", "ÅBC", "A" * 65])
def test_invalid_sku(client, new_product, sku):
    assert "sku" in errors(client.post("/api/products/", json=new_product | {"sku": sku}))


@pytest.mark.parametrize("field", ["id", "stock_quantity", "created_at", "is_active", "effective_price", "colour"])
def test_unknown_and_read_only_fields_are_rejected(client, new_product, field):
    assert errors(client.post("/api/products/", json=new_product | {field: 1}))[field] == "Extra inputs are not permitted"


# SKU uniqueness

def test_duplicate_sku_is_409_ignoring_case(client, new_product, db_session):
    client.post("/api/products/", json=new_product)
    before = product_count(db_session)
    response = client.post("/api/products/", json=new_product | {"sku": "tee-red-m", "name": "Other"})
    assert response.status_code == 409
    assert response.json() == DUPLICATE_SKU
    assert product_count(db_session) == before


def test_duplicate_found_only_by_the_database_is_409(client, new_product, monkeypatch, db_session):
    """Two requests racing: the service check passes for both, the unique constraint stops one."""
    client.post("/api/products/", json=new_product | {"initial_stock": 5})
    monkeypatch.setattr(product_service, "_check_sku", lambda *args, **kwargs: None)
    before = product_count(db_session)
    transactions = db_session.scalar(select(func.count()).select_from(InventoryTransaction))

    response = client.post("/api/products/", json=new_product | {"initial_stock": 5})
    assert response.status_code == 409
    assert response.json() == DUPLICATE_SKU
    # Nothing from the failed request was kept, not even its initial-stock transaction.
    assert product_count(db_session) == before
    assert db_session.scalar(select(func.count()).select_from(InventoryTransaction)) == transactions


def test_database_errors_reveal_no_internals(client, new_product, monkeypatch):
    client.post("/api/products/", json=new_product)
    monkeypatch.setattr(product_service, "_check_sku", lambda *args, **kwargs: None)
    response = client.post("/api/products/", json=new_product)
    for internal in ("INSERT", "products", "uq_", "Duplicate entry", "UNIQUE", "IntegrityError", "TEE-RED-M"):
        assert internal not in response.text, internal


def test_other_integrity_errors_get_a_generic_conflict():
    class FakeSession:
        rolled_back = False

        def commit(self):
            raise IntegrityError("UPDATE products ...", {}, Exception(3819, "Check constraint 'x' is violated."))

        def rollback(self):
            self.rolled_back = True

    session = FakeSession()
    with pytest.raises(product_service.ConflictError) as caught:
        with product_service._write(session):
            pass
    assert caught.value.message == "The product could not be saved because it conflicts with existing data"
    assert session.rolled_back


# Category rules

def test_category_must_exist(client, new_product):
    response = client.post("/api/products/", json=new_product | {"category_id": MISSING_ID})
    assert errors(response) == {"category_id": "category_id does not refer to an existing category"}


def test_category_must_be_active(client, category, new_product, db_session):
    client.patch(f"/api/categories/{category['id']}", json={"is_active": False})
    response = client.post("/api/products/", json=new_product)
    assert errors(response) == {"category_id": "category_id refers to an inactive category"}
    assert product_count(db_session) == 0


# Money

def test_money_is_exact_decimal(make_product):
    assert make_product(price="0.10")["price"] == "0.10"  # a string, never the float 0.1


@pytest.mark.parametrize(("sent", "stored"), [
    ("19.5", "19.50"), ("7", "7.00"), (19.99, "19.99"), (5, "5.00"), ("0", "0.00"), ("-0.00", "0.00"),
    ("99999999.99", "99999999.99"),
])
def test_price_formats(client, new_product, sent, stored):
    response = client.post("/api/products/", json=new_product | {"price": sent})
    assert response.status_code == 201, response.text
    assert response.json()["price"] == stored


@pytest.mark.parametrize(("price", "message"), [
    ("-1", "Input should be greater than or equal to 0"),
    ("-0.01", "Input should be greater than or equal to 0"),
    ("1.999", "Decimal input should have no more than 2 decimal places"),
    ("100000000.00", "Decimal input should have no more than 8 digits before the decimal point"),
    ("NaN", "Input should be a finite number"),
    ("Infinity", "Input should be a finite number"),
    ("abc", "Input should be a valid decimal"),
    (None, "Decimal input should be an integer, float, string or Decimal object"),
])
def test_invalid_prices(client, new_product, price, message):
    assert errors(client.post("/api/products/", json=new_product | {"price": price})) == {"price": message}


@pytest.mark.parametrize("discount", ["10.00", "12.00"])
def test_discount_must_be_below_price(client, new_product, discount):
    response = client.post("/api/products/", json=new_product | {"price": "10.00", "discount_price": discount})
    assert errors(response) == {"discount_price": DISCOUNT_MESSAGE}


def test_negative_discount_is_refused(client, new_product):
    response = client.post("/api/products/", json=new_product | {"discount_price": "-1.00"})
    assert errors(response) == {"discount_price": "Input should be greater than or equal to 0"}


def test_valid_discounts(client, new_product):
    body = new_product | {"price": "10.00"}
    assert client.post("/api/products/", json=body | {"discount_price": "9.99"}).status_code == 201
    assert client.post("/api/products/", json=body | {"sku": "FREE-1", "discount_price": "0"}).json()[
        "effective_price"] == "0.00"


def test_bad_price_is_reported_once(client, new_product):
    """An invalid price is reported on price; the discount check is skipped, not reported twice."""
    response = client.post("/api/products/", json=new_product | {"price": "-5", "discount_price": "1.00"})
    assert errors(response) == {"price": "Input should be greater than or equal to 0"}


# Stock

def test_initial_stock_is_recorded_as_a_transaction(client, make_product):
    product = make_product(initial_stock=7)
    history = client.get(f"/api/inventory/{product['id']}/history").json()
    assert history["total"] == 1
    entry = history["items"][0]
    assert (entry["transaction_type"], entry["quantity"], entry["previous_stock"], entry["updated_stock"]) == ("IN", 7, 0, 7)
    assert entry["remarks"] == "Initial stock"


def test_zero_initial_stock_records_no_transaction(client, make_product):
    product = make_product(initial_stock=0)
    assert product["stock_quantity"] == 0
    assert client.get(f"/api/inventory/{product['id']}/history").json()["total"] == 0


@pytest.mark.parametrize(("stock", "message"), [
    (-1, "Input should be greater than or equal to 0"),
    (1_000_000_001, "Input should be less than or equal to 1000000000"),
    ("lots", "Input should be a valid integer, unable to parse string as an integer"),
    (1.5, "Input should be a valid integer, got a number with a fractional part"),
])
def test_initial_stock_cannot_be_negative_or_invalid(client, new_product, stock, message):
    assert errors(client.post("/api/products/", json=new_product | {"initial_stock": stock})) == {"initial_stock": message}


# Malformed requests (400)

@pytest.mark.parametrize(("kwargs", "message"), [
    ({"content": b'{"sku": "A",', "headers": {"Content-Type": "application/json"}}, "Request body is not valid JSON"),
    ({}, "Request body is required"),
    ({"json": ["not", "an", "object"]}, "Request body must be a JSON object sent with Content-Type: application/json"),
    ({"data": {"sku": "A"}}, "Request body must be a JSON object sent with Content-Type: application/json"),
])
def test_malformed_body_is_400(client, kwargs, message):
    response = client.post("/api/products/", **kwargs)
    assert response.status_code == 400
    assert response.json() == {"detail": message}


# --- GET /api/products/ ---

@pytest.fixture
def mixed_catalog(client, category, make_product) -> dict:
    """Visible, inactive, and in an inactive category."""
    visible = make_product(name="Visible")
    hidden = make_product(name="Hidden")
    client.delete(f"/api/products/{hidden['id']}")
    closed = client.post("/api/categories/", json={"name": "Closed"}).json()
    in_closed = make_product(name="In closed category", category_id=closed["id"])
    client.patch(f"/api/categories/{closed['id']}", json={"is_active": False})
    return {"visible": visible, "hidden": hidden, "in_closed": in_closed, "closed": closed}


def test_customers_and_visitors_see_only_active_products_in_active_categories(client, auth_as, mixed_catalog):
    for caller in (lambda: as_customer(auth_as), lambda: auth_as(None)):
        caller()
        page = client.get("/api/products/").json()
        assert [p["id"] for p in page["items"]] == [mixed_catalog["visible"]["id"]]
        assert page["total"] == 1
        # Filtering by the inactive category does not reveal its products.
        assert client.get("/api/products/", params={"category_id": mixed_catalog["closed"]["id"]}).json()["total"] == 0
        assert client.get("/api/products/", params={"search": "hidden"}).json()["total"] == 0


def test_admin_sees_everything_only_when_asking(client, mixed_catalog):
    assert client.get("/api/products/").json()["total"] == 1
    page = client.get("/api/products/", params={"include_inactive": True}).json()
    assert page["total"] == 3


def test_include_inactive_needs_admin(client, auth_as):
    auth_as(None)
    assert client.get("/api/products/", params={"include_inactive": True}).status_code == 401
    as_customer(auth_as)
    response = client.get("/api/products/", params={"include_inactive": True})
    assert response.status_code == 403
    assert response.json() == {"detail": "Admin role required"}


# --- GET /api/products/{id} ---

def test_get_product_is_public(client, auth_as, make_product):
    product = make_product()
    for caller in (lambda: auth_as(None), lambda: as_customer(auth_as)):
        caller()
        response = client.get(f"/api/products/{product['id']}")
        assert response.status_code == 200
        assert response.json() == product


def test_missing_product_is_404(client):
    response = client.get(f"/api/products/{MISSING_ID}")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_hidden_products_are_404_for_customers(client, auth_as, mixed_catalog):
    as_customer(auth_as)
    for key in ("hidden", "in_closed"):
        response = client.get(f"/api/products/{mixed_catalog[key]['id']}")
        assert response.status_code == 404
        assert response.json() == NOT_FOUND  # same as a missing product: nothing is revealed
    auth_as.admin()
    for key in ("hidden", "in_closed"):
        assert client.get(f"/api/products/{mixed_catalog[key]['id']}", params={"include_inactive": True}).status_code == 200


@pytest.mark.parametrize("bad_id", ["0", "-1", "abc", "1.5", "2147483648"])
def test_invalid_ids_are_422_on_every_endpoint(client, make_product, bad_id):
    product = make_product()
    path = f"/api/products/{bad_id}"
    for response in (
        client.get(path),
        client.put(path, json=full_body(product)),
        client.patch(path, json={"name": "X"}),
        client.delete(path),
    ):
        assert "product_id" in errors(response)


# --- PUT /api/products/{id} ---

def test_put_replaces_every_field(client, category, make_product):
    product = make_product(brand="Old", description="Old text", initial_stock=4)
    other = client.post("/api/categories/", json={"name": "Bags"}).json()
    body = full_body(product, category_id=other["id"], name="New Name", sku="new-sku", price="25.00",
                     discount_price="20.00", description=None, image_url=None, brand=None)
    response = client.put(f"/api/products/{product['id']}", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["category_id"], result["name"], result["sku"], result["price"], result["discount_price"]) == (
        other["id"], "New Name", "NEW-SKU", "25.00", "20.00")
    assert (result["description"], result["image_url"], result["brand"]) == (None, None, None)
    assert result["stock_quantity"] == 4  # stock untouched
    assert result["created_at"] == product["created_at"]


def test_put_requires_every_field(client, make_product):
    product = make_product()
    response = client.put(f"/api/products/{product['id']}", json={"name": "Only a name"})
    assert set(errors(response)) == {"category_id", "description", "sku", "price", "discount_price",
                                     "image_url", "brand", "is_active"}


def test_put_cannot_set_stock(client, make_product):
    product = make_product()
    response = client.put(f"/api/products/{product['id']}", json=full_body(product, stock_quantity=999))
    assert errors(response) == {"stock_quantity": "Extra inputs are not permitted"}


def test_put_checks_discount_sku_and_category(client, category, make_product):
    taken = make_product(sku="TAKEN")
    product = make_product()
    path = f"/api/products/{product['id']}"
    assert errors(client.put(path, json=full_body(product, price="10.00", discount_price="10.00"))) == {
        "discount_price": DISCOUNT_MESSAGE}
    response = client.put(path, json=full_body(product, sku="taken"))
    assert response.status_code == 409 and response.json() == DUPLICATE_SKU
    assert errors(client.put(path, json=full_body(product, category_id=MISSING_ID))) == {
        "category_id": "category_id does not refer to an existing category"}
    closed = client.post("/api/categories/", json={"name": "Closed"}).json()
    client.patch(f"/api/categories/{closed['id']}", json={"is_active": False})
    assert errors(client.put(path, json=full_body(product, category_id=closed["id"]))) == {
        "category_id": "category_id refers to an inactive category"}
    # Nothing was changed by the refused requests; keeping its own SKU is fine.
    assert client.get(path).json() == product
    assert taken["sku"] == "TAKEN"
    assert client.put(path, json=full_body(product, sku=product["sku"].lower())).status_code == 200


def test_put_deactivates_and_reactivates(client, auth_as, make_product):
    product = make_product()
    path = f"/api/products/{product['id']}"
    assert client.put(path, json=full_body(product, is_active=False)).json()["is_active"] is False
    as_customer(auth_as)
    assert client.get(path).status_code == 404
    auth_as.admin()
    assert client.put(path, json=full_body(product, is_active=True)).json()["is_active"] is True
    as_customer(auth_as)
    assert client.get(path).status_code == 200


def test_put_missing_product_is_404(client, make_product):
    product = make_product()
    response = client.put(f"/api/products/{MISSING_ID}", json=full_body(product))
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


# --- PATCH /api/products/{id} ---

def test_patch_changes_only_the_fields_sent(client, make_product):
    product = make_product(brand="Stride")
    response = client.patch(f"/api/products/{product['id']}", json={"price": "59.00", "description": "Light"})
    assert response.status_code == 200
    body = response.json()
    assert (body["price"], body["description"], body["brand"], body["name"]) == ("59.00", "Light", "Stride", product["name"])


def test_patch_null_rules(client, make_product):
    product = make_product(brand="Stride", discount_price="10.00")
    path = f"/api/products/{product['id']}"
    for field in ("category_id", "name", "sku", "price", "is_active"):
        assert errors(client.patch(path, json={field: None})) == {field: "cannot be null"}
    cleared = client.patch(path, json={"brand": None, "discount_price": None, "description": None}).json()
    assert (cleared["brand"], cleared["discount_price"], cleared["effective_price"]) == (None, None, product["price"])
    assert errors(client.patch(path, json={})) == {"body": "Send at least one field to update"}


def test_discount_is_checked_against_stored_price_on_update(client, make_product):
    product = make_product(price="50.00")
    path = f"/api/products/{product['id']}"

    assert errors(client.patch(path, json={"discount_price": "60.00"})) == {"discount_price": DISCOUNT_MESSAGE}
    assert client.patch(path, json={"discount_price": "40.00"}).status_code == 200
    # Lowering the price below the existing discount is refused too.
    assert errors(client.patch(path, json={"price": "30.00"})) == {"discount_price": DISCOUNT_MESSAGE}
    # Both together are checked against each other.
    assert client.patch(path, json={"price": "30.00", "discount_price": "25.00"}).status_code == 200


def test_patch_sku_and_category_rules(client, make_product):
    make_product(sku="TAKEN")
    product = make_product()
    path = f"/api/products/{product['id']}"
    response = client.patch(path, json={"sku": "taken"})
    assert response.status_code == 409 and response.json() == DUPLICATE_SKU
    assert client.patch(path, json={"sku": product["sku"]}).status_code == 200
    assert errors(client.patch(path, json={"category_id": MISSING_ID})) == {
        "category_id": "category_id does not refer to an existing category"}


def test_stock_quantity_cannot_be_set_directly(client, make_product):
    product = make_product()
    response = client.patch(f"/api/products/{product['id']}", json={"stock_quantity": -5})
    assert errors(response) == {"stock_quantity": "Extra inputs are not permitted"}


def test_patch_missing_product_is_404(client):
    assert client.patch(f"/api/products/{MISSING_ID}", json={"name": "x"}).json() == NOT_FOUND


# --- DELETE /api/products/{id} ---

def test_delete_deactivates_and_keeps_history(client, auth_as, make_product, db_session):
    product = make_product(initial_stock=3)
    response = client.delete(f"/api/products/{product['id']}")
    assert response.status_code == 200
    assert response.json() == {"message": "Product deactivated"}

    stored = client.get(f"/api/products/{product['id']}", params={"include_inactive": True}).json()
    assert stored["is_active"] is False and stored["stock_quantity"] == 3
    assert client.get(f"/api/inventory/{product['id']}/history").json()["total"] == 1
    assert product_count(db_session) == 1  # the row is kept

    auth_as(None)
    assert client.get(f"/api/products/{product['id']}").status_code == 404
    assert client.get("/api/products/").json()["total"] == 0


def test_delete_twice_is_harmless(client, make_product):
    product = make_product()
    assert client.delete(f"/api/products/{product['id']}").status_code == 200
    assert client.delete(f"/api/products/{product['id']}").status_code == 200


def test_reactivate_with_patch(client, auth_as, make_product):
    product = make_product()
    client.delete(f"/api/products/{product['id']}")
    assert client.patch(f"/api/products/{product['id']}", json={"is_active": True}).json()["is_active"] is True
    auth_as(None)
    assert client.get(f"/api/products/{product['id']}").status_code == 200


def test_reactivated_product_in_inactive_category_stays_hidden(client, auth_as, category, make_product):
    product = make_product()
    client.delete(f"/api/products/{product['id']}")
    client.patch(f"/api/categories/{category['id']}", json={"is_active": False})
    assert client.patch(f"/api/products/{product['id']}", json={"is_active": True}).status_code == 200
    as_customer(auth_as)
    assert client.get(f"/api/products/{product['id']}").status_code == 404


def test_delete_missing_product_is_404(client):
    response = client.delete(f"/api/products/{MISSING_ID}")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


# --- Unauthorized access to the write endpoints ---

def write_requests(product: dict) -> list[tuple[str, str, dict | None]]:
    path = f"/api/products/{product['id']}"
    new = {"sku": "NEW-1", "name": "New", "price": "1.00", "category_id": product["category_id"]}
    return [
        ("post", "/api/products/", new),
        ("post", "/api/products", new),
        ("put", path, full_body(product, name="Changed")),
        ("patch", path, {"name": "Changed"}),
        ("delete", path, None),
    ]


def test_writes_need_a_token(client, auth_as, make_product, db_session):
    product = make_product()
    auth_as(None)
    for method, path, body in write_requests(product):
        response = client.request(method, path, **({"json": body} if body else {}))
        assert response.status_code == 401, (method, path)
        assert response.json() == {"detail": "Could not validate credentials"}
        assert response.headers["WWW-Authenticate"] == "Bearer"
    assert client.get(f"/api/products/{product['id']}").json() == product
    assert product_count(db_session) == 1


def test_customers_cannot_write(client, auth_as, make_product, db_session):
    product = make_product()
    as_customer(auth_as)
    for method, path, body in write_requests(product):
        response = client.request(method, path, **({"json": body} if body else {}))
        assert response.status_code == 403, (method, path)
        assert response.json() == {"detail": "Admin role required"}
    assert client.get(f"/api/products/{product['id']}").json() == product
    assert product_count(db_session) == 1


def test_customers_see_prices_as_decimals(client, auth_as, make_product):
    product = make_product(price="1234.50", discount_price="999.99")
    as_customer(auth_as)
    body = client.get(f"/api/products/{product['id']}").json()
    assert Decimal(body["price"]) == Decimal("1234.50")
    assert (body["price"], body["effective_price"]) == ("1234.50", "999.99")
