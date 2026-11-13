"""Category endpoints: POST/GET /api/categories/, GET/PUT/PATCH/DELETE /api/categories/{id}.

The caller is switched with auth_as: an admin by default, auth_as(None) for an anonymous
visitor, auth_as(7, role="USER") for a customer (the Authentication Service's customer role).
"""

import os

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.category_model import Category
from app.services import category_service

USE_MYSQL = os.environ.get("CATALOG_SERVICE_TEST_DB", "").lower() == "mysql"  # same switch as conftest.py

CUSTOMER_ID = 7
MISSING_ID = 12345
DUPLICATE = {"detail": "A category with this name already exists"}


def as_customer(auth_as) -> None:
    auth_as(CUSTOMER_ID, role="USER")


def errors(response) -> dict[str, str]:
    """422 body as {field: message}."""
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["detail"] == "Validation failed"
    return {error["field"]: error["message"] for error in body["errors"]}


def category_count(db_session) -> int:
    return db_session.scalar(select(func.count()).select_from(Category))


# --- POST /api/categories/ ---

def test_create_category(client):
    response = client.post("/api/categories/", json={"name": "Electronics", "description": "Phones\nand laptops"})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Electronics"
    assert body["description"] == "Phones\nand laptops"
    assert body["is_active"] is True
    assert set(body) == {"id", "name", "description", "is_active", "created_at", "updated_at"}


@pytest.mark.parametrize("path", ["/api/categories/", "/api/categories"])
def test_collection_is_served_with_and_without_slash(client, path):
    response = client.post(path, json={"name": f"Category {len(path)}"}, follow_redirects=False)
    assert response.status_code == 201
    assert client.get(path, follow_redirects=False).status_code == 200


def test_description_is_optional(client):
    assert client.post("/api/categories/", json={"name": "Toys"}).json()["description"] is None


def test_timestamps_are_utc_in_responses(category):
    assert category["created_at"].endswith(("Z", "+00:00"))
    assert category["updated_at"].endswith(("Z", "+00:00"))


def test_name_whitespace_is_normalised(client):
    response = client.post("/api/categories/", json={"name": "  Running     Shoes  "})
    assert response.status_code == 201
    assert response.json()["name"] == "Running Shoes"


@pytest.mark.parametrize(("body", "field", "message"), [
    ({}, "name", "Field required"),
    ({"name": ""}, "name", "String should have at least 1 character"),
    ({"name": "   "}, "name", "String should have at least 1 character"),
    ({"name": "x" * 101}, "name", "String should have at most 100 characters"),
    ({"name": "---"}, "name", "must contain at least one letter or digit"),
    ({"name": "Shoes\x00"}, "name", "must not contain control characters"),
    ({"name": "Two\nlines"}, "name", "must not contain control characters"),
    ({"name": "Tab\tname"}, "name", "must not contain control characters"),
    ({"name": 123}, "name", "Input should be a valid string"),
    ({"name": "Toys", "description": "x" * 5001}, "description", "String should have at most 5000 characters"),
    ({"name": "Toys", "description": "bad\x07bell"}, "description", "must not contain control characters"),
])
def test_invalid_data_gets_a_clear_message(client, body, field, message):
    assert errors(client.post("/api/categories/", json=body)) == {field: message}


@pytest.mark.parametrize("field", ["id", "slug", "parent_id", "created_at", "is_active"])
def test_unknown_or_read_only_fields_are_rejected(client, field):
    assert field in errors(client.post("/api/categories/", json={"name": "X", field: 1}))


def test_body_must_be_json(client):
    response = client.post("/api/categories/", content=b"{not json", headers={"Content-Type": "application/json"})
    assert response.status_code == 400
    assert response.json() == {"detail": "Request body is not valid JSON"}


def test_duplicate_name_is_rejected_ignoring_case_and_spacing(client, category, db_session):
    before = category_count(db_session)
    for name in ("Footwear", "FOOTWEAR", "  footwear "):
        response = client.post("/api/categories/", json={"name": name})
        assert response.status_code == 409, name
        assert response.json() == DUPLICATE
    assert category_count(db_session) == before  # nothing was written


def test_duplicate_found_only_by_the_database_is_409(client, category, monkeypatch, db_session):
    """Two requests racing: the service check passes for both, the unique constraint stops one."""
    monkeypatch.setattr(category_service, "_check_unique_name", lambda *args, **kwargs: None)
    before = category_count(db_session)
    response = client.post("/api/categories/", json={"name": category["name"]})
    assert response.status_code == 409
    assert response.json() == DUPLICATE
    assert category_count(db_session) == before
    # The session was rolled back and is usable again.
    assert client.post("/api/categories/", json={"name": "Bags"}).status_code == 201


@pytest.mark.skipif(not USE_MYSQL, reason="MySQL collation behaviour")
def test_mysql_treats_accented_names_as_duplicates(client):
    """utf8mb4_0900_ai_ci ignores accents: the unique constraint refuses "Cafe" after "Café"."""
    assert client.post("/api/categories/", json={"name": "Café"}).status_code == 201
    response = client.post("/api/categories/", json={"name": "Cafe"})
    assert response.status_code == 409
    assert response.json() == DUPLICATE


def test_other_integrity_errors_get_a_generic_conflict():
    class FakeSession:
        rolled_back = False

        def commit(self):
            raise IntegrityError("INSERT ...", {}, Exception(3819, "Check constraint violated"))

        def rollback(self):
            self.rolled_back = True

    session = FakeSession()
    with pytest.raises(category_service.ConflictError) as caught:
        category_service._commit(session)
    assert caught.value.message == "The category could not be saved because it conflicts with existing data"
    assert session.rolled_back


# --- GET /api/categories/ ---

def test_list_is_sorted_by_name(client):
    for name in ("Toys", "Books", "Garden"):
        client.post("/api/categories/", json={"name": name})
    assert [c["name"] for c in client.get("/api/categories/").json()] == ["Books", "Garden", "Toys"]


def test_customers_and_visitors_see_only_active_categories(client, auth_as, category):
    hidden = client.post("/api/categories/", json={"name": "Old stock"}).json()
    client.patch(f"/api/categories/{hidden['id']}", json={"is_active": False})

    for caller in (lambda: as_customer(auth_as), lambda: auth_as(None)):
        caller()
        response = client.get("/api/categories/")
        assert response.status_code == 200
        assert [c["id"] for c in response.json()] == [category["id"]]

    auth_as.admin()
    assert [c["id"] for c in client.get("/api/categories/").json()] == [category["id"]]  # default: active only
    listed = client.get("/api/categories/", params={"include_inactive": True}).json()
    assert {c["id"] for c in listed} == {category["id"], hidden["id"]}


def test_include_inactive_needs_admin(client, auth_as):
    auth_as(None)
    assert client.get("/api/categories/", params={"include_inactive": True}).status_code == 401
    as_customer(auth_as)
    response = client.get("/api/categories/", params={"include_inactive": True})
    assert response.status_code == 403
    assert response.json() == {"detail": "Admin role required"}


def test_include_inactive_must_be_a_boolean(client):
    assert "include_inactive" in errors(client.get("/api/categories/", params={"include_inactive": "maybe"}))


# --- GET /api/categories/{id} ---

def test_get_category(client, auth_as, category):
    for caller in (lambda: as_customer(auth_as), lambda: auth_as(None), auth_as.admin):
        caller()
        response = client.get(f"/api/categories/{category['id']}")
        assert response.status_code == 200
        assert response.json() == category


def test_inactive_category_is_404_except_for_admin_with_include_inactive(client, auth_as, category):
    client.patch(f"/api/categories/{category['id']}", json={"is_active": False})
    path = f"/api/categories/{category['id']}"

    as_customer(auth_as)
    assert client.get(path).status_code == 404
    assert client.get(path, params={"include_inactive": True}).status_code == 403
    auth_as(None)
    assert client.get(path).status_code == 404

    auth_as.admin()
    assert client.get(path).status_code == 404
    assert client.get(path, params={"include_inactive": True}).json()["is_active"] is False


def test_missing_category_is_404(client):
    response = client.get(f"/api/categories/{MISSING_ID}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Category not found"}


@pytest.mark.parametrize("bad_id", ["0", "-1", "abc", "1.5", "2147483648"])
def test_invalid_ids_are_422_on_every_endpoint(client, bad_id):
    path = f"/api/categories/{bad_id}"
    full = {"name": "X", "description": None, "is_active": True}
    for response in (
        client.get(path),
        client.put(path, json=full),
        client.patch(path, json={"name": "X"}),
        client.delete(path),
    ):
        assert "category_id" in errors(response)


# --- PUT /api/categories/{id} ---

def test_put_replaces_every_field(client, category):
    response = client.put(f"/api/categories/{category['id']}",
                          json={"name": "Shoes", "description": "All shoes", "is_active": True})
    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["description"], body["is_active"]) == ("Shoes", "All shoes", True)
    assert body["created_at"] == category["created_at"]
    assert client.get(f"/api/categories/{category['id']}").json()["name"] == "Shoes"


def test_put_requires_every_field(client, category):
    response = client.put(f"/api/categories/{category['id']}", json={"name": "Shoes"})
    assert errors(response) == {"description": "Field required", "is_active": "Field required"}


def test_put_with_null_description_clears_it(client, category):
    assert category["description"] is not None
    response = client.put(f"/api/categories/{category['id']}",
                          json={"name": "Footwear", "description": None, "is_active": True})
    assert response.json()["description"] is None


def test_put_validates_like_create(client, category):
    path = f"/api/categories/{category['id']}"
    assert errors(client.put(path, json={"name": "***", "description": None, "is_active": True})) == {
        "name": "must contain at least one letter or digit"}
    assert "is_active" in errors(client.put(path, json={"name": "A", "description": None, "is_active": "sometimes"}))
    assert "id" in errors(client.put(path, json={"name": "A", "description": None, "is_active": True, "id": 9}))


def test_put_rename_to_existing_name_is_409(client, category):
    other = client.post("/api/categories/", json={"name": "Bags"}).json()
    response = client.put(f"/api/categories/{other['id']}",
                          json={"name": "FOOTWEAR", "description": None, "is_active": True})
    assert response.status_code == 409
    assert response.json() == DUPLICATE
    assert client.get(f"/api/categories/{other['id']}").json()["name"] == "Bags"  # unchanged
    # Keeping its own name, in another case, is allowed.
    response = client.put(f"/api/categories/{category['id']}",
                          json={"name": "FOOTWEAR", "description": None, "is_active": True})
    assert response.status_code == 200


def test_put_deactivates_and_reactivates(client, auth_as, category, make_product):
    product = make_product()
    path = f"/api/categories/{category['id']}"
    assert client.put(path, json={"name": "Footwear", "description": None, "is_active": False}).status_code == 200

    as_customer(auth_as)
    assert client.get("/api/categories/").json() == []
    assert client.get("/api/products").json()["total"] == 0  # its products are hidden too
    assert client.get(f"/api/products/{product['id']}").status_code == 404

    auth_as.admin()
    # PUT works on an inactive category, and brings it back.
    assert client.put(path, json={"name": "Footwear", "description": None, "is_active": True}).status_code == 200
    as_customer(auth_as)
    assert [c["id"] for c in client.get("/api/categories/").json()] == [category["id"]]
    assert client.get("/api/products").json()["total"] == 1


def test_put_missing_category_is_404(client):
    response = client.put(f"/api/categories/{MISSING_ID}", json={"name": "X", "description": None, "is_active": True})
    assert response.status_code == 404


# --- PATCH /api/categories/{id} ---

def test_patch_changes_only_the_fields_sent(client, category):
    response = client.patch(f"/api/categories/{category['id']}", json={"description": None})
    assert response.status_code == 200
    body = response.json()
    assert body["description"] is None
    assert (body["name"], body["is_active"]) == (category["name"], True)


def test_patch_rename_to_existing_name_is_409(client, category):
    other = client.post("/api/categories/", json={"name": "Bags"}).json()
    assert client.patch(f"/api/categories/{other['id']}", json={"name": "footwear"}).status_code == 409


def test_patch_requires_a_field_and_rejects_null_name(client, category):
    path = f"/api/categories/{category['id']}"
    assert errors(client.patch(path, json={})) == {"body": "Send at least one field to update"}
    assert errors(client.patch(path, json={"name": None})) == {"name": "cannot be null"}
    assert errors(client.patch(path, json={"is_active": None})) == {"is_active": "cannot be null"}


def test_patch_missing_category_is_404(client):
    assert client.patch(f"/api/categories/{MISSING_ID}", json={"name": "x"}).status_code == 404


# --- DELETE /api/categories/{id} ---

def test_delete_empty_category(client, category):
    response = client.delete(f"/api/categories/{category['id']}")
    assert response.status_code == 200
    assert response.json() == {"message": "Category deleted"}
    assert client.get(f"/api/categories/{category['id']}", params={"include_inactive": True}).status_code == 404
    assert client.delete(f"/api/categories/{category['id']}").status_code == 404


def test_delete_inactive_empty_category(client, category):
    client.patch(f"/api/categories/{category['id']}", json={"is_active": False})
    assert client.delete(f"/api/categories/{category['id']}").status_code == 200


def test_delete_category_with_products_is_refused(client, category, make_product):
    make_product()
    make_product()
    response = client.delete(f"/api/categories/{category['id']}")
    assert response.status_code == 409
    assert response.json() == {"detail": "Category still contains 2 products (active or inactive). Move them "
                                         "to another category, or deactivate the category instead of deleting it"}
    assert client.get(f"/api/categories/{category['id']}").status_code == 200  # still there


def test_inactive_products_also_block_deletion(client, category, make_product):
    product = make_product()
    client.delete(f"/api/products/{product['id']}")  # deactivates the product
    response = client.delete(f"/api/categories/{category['id']}")
    assert response.status_code == 409
    assert "1 product (active or inactive). Move it" in response.json()["detail"]


def test_delete_after_moving_products_away(client, category, make_product):
    product = make_product()
    other = client.post("/api/categories/", json={"name": "Bags"}).json()
    assert client.patch(f"/api/products/{product['id']}", json={"category_id": other["id"]}).status_code == 200
    assert client.delete(f"/api/categories/{category['id']}").status_code == 200
    assert client.get(f"/api/products/{product['id']}").json()["category_id"] == other["id"]


def test_delete_race_is_stopped_by_the_foreign_key(client, category, make_product, monkeypatch):
    """A product added after the check: the database foreign key (RESTRICT) refuses the delete."""
    make_product()
    real_count = category_service._product_count
    calls = []

    def count_that_misses_the_first_time(db, category_id):
        calls.append(category_id)
        return 0 if len(calls) == 1 else real_count(db, category_id)

    monkeypatch.setattr(category_service, "_product_count", count_that_misses_the_first_time)
    response = client.delete(f"/api/categories/{category['id']}")
    assert response.status_code == 409
    assert "Category still contains 1 product" in response.json()["detail"]
    assert client.get(f"/api/categories/{category['id']}").status_code == 200


def test_delete_missing_category_is_404(client):
    assert client.delete(f"/api/categories/{MISSING_ID}").status_code == 404


# --- Unauthorized access to the write endpoints ---

def write_requests(category_id: int) -> list[tuple[str, str, dict | None]]:
    return [
        ("post", "/api/categories/", {"name": "New"}),
        ("post", "/api/categories", {"name": "New"}),
        ("put", f"/api/categories/{category_id}", {"name": "New", "description": None, "is_active": True}),
        ("patch", f"/api/categories/{category_id}", {"name": "New"}),
        ("delete", f"/api/categories/{category_id}", None),
    ]


def test_writes_need_a_token(client, auth_as, category, db_session):
    auth_as(None)
    for method, path, body in write_requests(category["id"]):
        response = client.request(method, path, **({"json": body} if body else {}))
        assert response.status_code == 401, (method, path)
        assert response.json() == {"detail": "Could not validate credentials"}
        assert response.headers["WWW-Authenticate"] == "Bearer"
    assert category_count(db_session) == 1


def test_customers_cannot_write(client, auth_as, category, db_session):
    as_customer(auth_as)
    for method, path, body in write_requests(category["id"]):
        response = client.request(method, path, **({"json": body} if body else {}))
        assert response.status_code == 403, (method, path)
        assert response.json() == {"detail": "Admin role required"}
    auth_as.admin()
    assert client.get(f"/api/categories/{category['id']}").json() == category  # unchanged
    assert category_count(db_session) == 1


def test_auth_is_checked_before_the_body(client, auth_as, category):
    """A visitor learns nothing about validation rules or which IDs exist."""
    auth_as(None)
    assert client.post("/api/categories/", json={"name": ""}).status_code == 401
    assert client.put(f"/api/categories/{MISSING_ID}", json={"name": "X", "description": None,
                                                              "is_active": True}).status_code == 401
