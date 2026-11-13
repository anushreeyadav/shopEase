"""GET /api/products/: search, filters, paging and sorting.

One fixed catalogue is built through the API. Every combination of search, category, price range
and availability is then requested and compared with a plain-Python reference that applies the
documented rules to the same data, for a customer and for an admin asking for inactive products.

The catalogue has products hidden both ways (inactive product, active product in an inactive
category), prices exactly on the 1000 / 5000 boundaries, stock 0, and an SKU-only search match.
"""

import itertools
import re
from decimal import Decimal

import pytest
from sqlalchemy import event

MISSING_CATEGORY_ID = 99_999
PAGE_FIELDS = {"items", "total", "page", "page_size", "total_pages"}

# name, sku, price, initial stock, category key, hidden by
CATALOGUE = [
    ("Galaxy Mobile", "MOB-100", "1500.00", 5, "phones", None),
    ("Pixel Mobile", "MOB-200", "4500.00", 0, "phones", None),
    ("Budget Phone", "PHN-300", "800.00", 12, "phones", None),
    ("Laptop Stand", "MOBILE-STAND-1", "1000.00", 0, "laptops", None),  # "mobile" only in the SKU
    ("Ultrabook", "LAP-500", "5000.00", 7, "laptops", None),
    ("Gaming Laptop", "LAP-600", "5000.01", 2, "laptops", None),
    ("Retired Mobile", "MOB-900", "2000.00", 4, "phones", "product inactive"),
    ("Archive Mobile", "MOB-950", "3000.00", 6, "archive", "category inactive"),
]

SEARCHES = [None, "mobile", "LAP", "mob-", "zzz"]
CATEGORIES = [None, "phones", "laptops", "archive", "missing"]
PRICE_RANGES = [(None, None), ("1000", "5000"), ("4500", None), (None, "999.99"), ("1500", "1500")]
AVAILABILITY = [None, "in_stock", "out_of_stock"]
SORTS = [(sort_by, order) for sort_by in ("name", "price", "created_at") for order in ("asc", "desc")]


def as_customer(auth_as) -> None:
    auth_as(7, role="USER")


def errors(response) -> dict[str, str]:
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["detail"] == "Validation failed"
    return {error["field"]: error["message"] for error in body["errors"]}


@pytest.fixture
def catalogue(client) -> dict:
    """Build CATALOGUE (as admin) and return the categories and the created products."""
    categories = {key: client.post("/api/categories/", json={"name": key.title()}).json()
                  for key in ("phones", "laptops", "archive")}
    products = []
    for name, sku, price, stock, category_key, hidden_by in CATALOGUE:
        response = client.post("/api/products/", json={
            "name": name, "sku": sku, "price": price, "initial_stock": stock,
            "category_id": categories[category_key]["id"],
        })
        assert response.status_code == 201, response.text
        product = response.json()
        if hidden_by == "product inactive":
            product = client.patch(f"/api/products/{product['id']}", json={"is_active": False}).json()
        products.append(product)
    assert client.patch(f"/api/categories/{categories['archive']['id']}", json={"is_active": False}).status_code == 200
    return {"categories": categories, "products": products}


def category_id(catalogue: dict, key: str | None) -> int | None:
    if key is None:
        return None
    return MISSING_CATEGORY_ID if key == "missing" else catalogue["categories"][key]["id"]


def reference(catalogue, *, search=None, category=None, min_price=None, max_price=None, availability=None,
              sort_by="name", sort_order="asc", include_inactive=False) -> list[str]:
    """The documented rules, applied in Python. Returns the expected SKUs in the expected order."""
    hidden = {sku for _, sku, _, _, _, hidden_by in CATALOGUE if hidden_by}
    wanted_category = category_id(catalogue, category)
    rows = []
    for product in catalogue["products"]:
        if not include_inactive and product["sku"] in hidden:
            continue
        if search and search.lower() not in product["name"].lower() and search.lower() not in product["sku"].lower():
            continue
        if wanted_category is not None and product["category_id"] != wanted_category:
            continue
        price = Decimal(product["price"])
        if min_price is not None and price < Decimal(min_price):
            continue
        if max_price is not None and price > Decimal(max_price):
            continue
        if availability == "in_stock" and product["stock_quantity"] == 0:
            continue
        if availability == "out_of_stock" and product["stock_quantity"] > 0:
            continue
        rows.append(product)
    key = {"name": lambda p: p["name"].lower(), "price": lambda p: Decimal(p["price"]),
           "created_at": lambda p: p["created_at"]}[sort_by]
    rows.sort(key=lambda p: (key(p), p["id"]), reverse=sort_order == "desc")
    return [p["sku"] for p in rows]


def query_params(catalogue, search, category, prices, availability, sort) -> dict:
    params = {
        "search": search,
        "category_id": category_id(catalogue, category),
        "min_price": prices[0],
        "max_price": prices[1],
        "availability": availability,
        "sort_by": sort[0],
        "sort_order": sort[1],
    }
    return {name: value for name, value in params.items() if value is not None}


def combinations():
    grid = itertools.product(SEARCHES, CATEGORIES, PRICE_RANGES, AVAILABILITY)
    # The sort is rotated through the grid, so every sort meets every kind of filter.
    for index, (search, category, prices, availability) in enumerate(grid):
        yield search, category, prices, availability, SORTS[index % len(SORTS)]


# --- Every filter combination ---

@pytest.mark.parametrize("caller", ["customer", "admin, include_inactive"])
def test_every_filter_combination(client, auth_as, catalogue, caller):
    include_inactive = caller != "customer"
    if not include_inactive:
        as_customer(auth_as)
    checked = 0
    for search, category, prices, availability, sort in combinations():
        params = query_params(catalogue, search, category, prices, availability, sort)
        if include_inactive:
            params["include_inactive"] = "true"
        response = client.get("/api/products/", params=params | {"page_size": 100})
        assert response.status_code == 200, (params, response.text)
        body = response.json()
        expected = reference(catalogue, search=search, category=category, min_price=prices[0],
                             max_price=prices[1], availability=availability, sort_by=sort[0],
                             sort_order=sort[1], include_inactive=include_inactive)
        assert [p["sku"] for p in body["items"]] == expected, params
        assert body["total"] == len(expected), params
        checked += 1
    assert checked == len(SEARCHES) * len(CATEGORIES) * len(PRICE_RANGES) * len(AVAILABILITY) == 375


def test_the_grid_is_not_trivial(catalogue):
    """Guards the combination test: the reference must give empty, partial and hidden-dependent results."""
    sizes = {len(reference(catalogue, search=s, category=c, min_price=p[0], max_price=p[1], availability=a))
             for s, c, p, a, _ in combinations()}
    assert {0, 1, 2, 3} <= sizes
    assert reference(catalogue, search="mobile") != reference(catalogue, search="mobile", include_inactive=True)


# --- Each filter on its own, with readable expectations ---

def skus(client, **params) -> list[str]:
    response = client.get("/api/products/", params=params)
    assert response.status_code == 200, response.text
    return [p["sku"] for p in response.json()["items"]]


def test_search_matches_name_or_sku_ignoring_case(client, catalogue):
    # Laptop Stand matches through its SKU only; the two hidden "Mobile" products are left out.
    assert skus(client, search="mobile") == ["MOB-100", "MOBILE-STAND-1", "MOB-200"]
    assert skus(client, search="MOBILE") == skus(client, search="mobile")
    assert skus(client, search="phn-3") == ["PHN-300"]
    assert skus(client, search="  ultra  ") == ["LAP-500"]  # surrounding spaces are ignored
    assert skus(client, search="zzz") == []


def test_search_treats_wildcards_literally(client, make_product):
    make_product(name="100% Cotton Tee")
    make_product(name="Plain Tee")
    make_product(name="Under_score Tee")
    assert [p["name"] for p in client.get("/api/products/", params={"search": "%"}).json()["items"]] == ["100% Cotton Tee"]
    assert [p["name"] for p in client.get("/api/products/", params={"search": "_"}).json()["items"]] == ["Under_score Tee"]


def test_filter_by_category(client, catalogue):
    phones = catalogue["categories"]["phones"]["id"]
    assert skus(client, category_id=phones) == ["PHN-300", "MOB-100", "MOB-200"]
    assert skus(client, category_id=MISSING_CATEGORY_ID) == []


def test_inactive_category_shows_nothing_to_customers(client, auth_as, catalogue):
    archive = catalogue["categories"]["archive"]["id"]
    assert skus(client, category_id=archive, include_inactive=True) == ["MOB-950"]  # admin
    as_customer(auth_as)
    assert skus(client, category_id=archive) == []


def test_price_range_is_inclusive(client, catalogue):
    assert skus(client, min_price="1000", max_price="5000") == ["MOB-100", "MOBILE-STAND-1", "MOB-200", "LAP-500"]
    assert skus(client, min_price="5000.01") == ["LAP-600"]
    assert skus(client, max_price="800") == ["PHN-300"]
    assert skus(client, min_price="1500", max_price="1500") == ["MOB-100"]


def test_price_filter_uses_the_normal_price(client, make_product):
    make_product(name="Discounted", price="100.00", discount_price="40.00")
    assert [p["name"] for p in client.get("/api/products/", params={"max_price": "50"}).json()["items"]] == []
    assert len(client.get("/api/products/", params={"min_price": "100"}).json()["items"]) == 1


def test_filter_by_availability(client, catalogue):
    assert skus(client, availability="out_of_stock") == ["MOBILE-STAND-1", "MOB-200"]
    assert skus(client, availability="in_stock") == ["PHN-300", "MOB-100", "LAP-600", "LAP-500"]


def test_stock_changes_move_a_product_between_availability_filters(client, catalogue):
    stand = next(p for p in catalogue["products"] if p["sku"] == "MOBILE-STAND-1")
    assert client.post(f"/api/inventory/{stand['id']}/stock-in", json={"quantity": 3}).status_code == 201
    assert "MOBILE-STAND-1" in skus(client, availability="in_stock")
    assert "MOBILE-STAND-1" not in skus(client, availability="out_of_stock")


def test_filter_by_brand(client, make_product):
    make_product(name="Road Shoe", brand="Stride")
    make_product(name="Trail Shoe", brand="Peak")
    assert [p["name"] for p in client.get("/api/products/", params={"brand": "stride"}).json()["items"]] == ["Road Shoe"]


def test_spec_examples(client, catalogue):
    """The example requests from the task, as written."""
    phones = catalogue["categories"]["phones"]["id"]
    assert client.get("/api/products/?search=mobile").json()["total"] == 3
    assert client.get(f"/api/products/?category_id={phones}").json()["total"] == 3
    assert client.get("/api/products/?min_price=1000&max_price=5000").json()["total"] == 4
    page = client.get("/api/products/?page=1&page_size=10").json()
    assert (page["page"], page["page_size"], page["total"], page["total_pages"]) == (1, 10, 6, 1)
    by_price = client.get("/api/products/?sort_by=price&sort_order=asc").json()["items"]
    assert [p["price"] for p in by_price] == ["800.00", "1000.00", "1500.00", "4500.00", "5000.00", "5000.01"]


# --- Sorting ---

@pytest.mark.parametrize("sort_by, sort_order", SORTS)
def test_sorting(client, catalogue, sort_by, sort_order):
    assert skus(client, sort_by=sort_by, sort_order=sort_order) == reference(
        catalogue, sort_by=sort_by, sort_order=sort_order)


def test_default_sort_is_name_ascending(client, catalogue):
    assert skus(client) == reference(catalogue, sort_by="name", sort_order="asc")
    assert skus(client)[0] == "PHN-300"  # Budget Phone


def test_price_sort_is_numeric_not_text(client, make_product):
    for price in ("9.99", "10.00", "100.00", "2.50"):
        make_product(name=f"Item {price}", price=price)
    prices = [p["price"] for p in client.get("/api/products/", params={"sort_by": "price"}).json()["items"]]
    assert prices == ["2.50", "9.99", "10.00", "100.00"]


def test_ties_are_broken_by_id_in_the_same_direction(client, make_product):
    ids = [make_product(name="Same Name", price="10.00")["id"] for _ in range(4)]
    for sort_by in ("name", "price", "created_at"):
        assert [p["id"] for p in client.get("/api/products/", params={"sort_by": sort_by}).json()["items"]] == ids
        newest_first = client.get("/api/products/", params={"sort_by": sort_by, "sort_order": "desc"}).json()
        assert [p["id"] for p in newest_first["items"]] == ids[::-1]


# --- Pagination ---

def test_page_metadata(client, catalogue):
    body = client.get("/api/products/", params={"page_size": 4}).json()
    assert set(body) == PAGE_FIELDS
    assert (body["total"], body["page"], body["page_size"], body["total_pages"]) == (6, 1, 4, 2)
    assert len(body["items"]) == 4
    second = client.get("/api/products/", params={"page_size": 4, "page": 2}).json()
    assert (second["page"], len(second["items"]), second["total_pages"]) == (2, 2, 2)


def test_defaults(client, catalogue):
    body = client.get("/api/products/").json()
    assert (body["page"], body["page_size"]) == (1, 20)


def test_pages_cover_every_product_exactly_once(client, catalogue):
    for sort_by, sort_order in SORTS:
        seen = []
        for page in (1, 2, 3):
            seen += skus(client, page=page, page_size=2, sort_by=sort_by, sort_order=sort_order)
        assert seen == reference(catalogue, sort_by=sort_by, sort_order=sort_order)


def test_paging_applies_after_filters(client, catalogue):
    body = client.get("/api/products/", params={"search": "mobile", "page_size": 2, "page": 2}).json()
    assert (body["total"], body["total_pages"], [p["sku"] for p in body["items"]]) == (3, 2, ["MOB-200"])


def test_page_past_the_end_is_empty_with_correct_totals(client, catalogue):
    body = client.get("/api/products/", params={"page": 50, "page_size": 10}).json()
    assert body == {"items": [], "total": 6, "page": 50, "page_size": 10, "total_pages": 1}


def test_no_matches(client, catalogue):
    body = client.get("/api/products/", params={"search": "zzz"}).json()
    assert body == {"items": [], "total": 0, "page": 1, "page_size": 20, "total_pages": 0}


def test_maximum_page_size(client, catalogue):
    assert client.get("/api/products/", params={"page_size": 100}).status_code == 200


# --- Visibility under every filter ---

def test_hidden_products_never_appear_for_anonymous_visitors(client, auth_as, catalogue):
    """Customers get the same check in test_every_filter_combination (exact lists)."""
    hidden = {sku for _, sku, _, _, _, hidden_by in CATALOGUE if hidden_by}
    auth_as(None)
    for search, category, prices, availability, sort in combinations():
        params = query_params(catalogue, search, category, prices, availability, sort)
        items = client.get("/api/products/", params=params | {"page_size": 100}).json()["items"]
        assert not hidden & {p["sku"] for p in items}, params
        assert all(p["is_active"] for p in items)


def test_search_for_a_hidden_product_by_exact_sku(client, auth_as, catalogue):
    as_customer(auth_as)
    assert skus(client, search="MOB-900") == []
    assert client.get("/api/products/", params={"search": "MOB-900"}).json()["total"] == 0


def test_include_inactive_needs_admin(client, auth_as, catalogue):
    auth_as(None)
    assert client.get("/api/products/", params={"include_inactive": "true", "search": "mobile"}).status_code == 401
    as_customer(auth_as)
    assert client.get("/api/products/", params={"include_inactive": "true", "search": "mobile"}).status_code == 403


# --- Query validation ---

@pytest.mark.parametrize("params, field, message", [
    ({"page": 0}, "page", "Input should be greater than or equal to 1"),
    ({"page": -1}, "page", "Input should be greater than or equal to 1"),
    ({"page": 100_001}, "page", "Input should be less than or equal to 100000"),
    ({"page": "two"}, "page", "Input should be a valid integer, unable to parse string as an integer"),
    ({"page": "1.5"}, "page", "Input should be a valid integer, unable to parse string as an integer"),
    ({"page_size": 0}, "page_size", "Input should be greater than or equal to 1"),
    ({"page_size": -10}, "page_size", "Input should be greater than or equal to 1"),
    ({"page_size": 101}, "page_size", "Input should be less than or equal to 100"),
    ({"sort_by": "id; DROP TABLE products"}, "sort_by", "Input should be 'name', 'price' or 'created_at'"),
    ({"sort_by": "stock_quantity"}, "sort_by", "Input should be 'name', 'price' or 'created_at'"),
    ({"sort_order": "up"}, "sort_order", "Input should be 'asc' or 'desc'"),
    ({"sort_order": "ASC"}, "sort_order", "Input should be 'asc' or 'desc'"),
    ({"availability": "maybe"}, "availability", "Input should be 'in_stock' or 'out_of_stock'"),
    ({"min_price": "-1"}, "min_price", "Input should be greater than or equal to 0"),
    ({"max_price": "abc"}, "max_price", "Input should be a valid decimal"),
    ({"min_price": "1.999"}, "min_price", "Decimal input should have no more than 2 decimal places"),
    ({"max_price": "nan"}, "max_price", "Input should be a finite number"),
    ({"min_price": "50", "max_price": "10"}, "max_price", "max_price must not be lower than min_price"),
    ({"category_id": "x"}, "category_id", "Input should be a valid integer, unable to parse string as an integer"),
    ({"category_id": 0}, "category_id", "Input should be greater than or equal to 1"),
    ({"category_id": 2**31}, "category_id", "Input should be less than or equal to 2147483647"),
    ({"search": "   "}, "search", "String should have at least 1 character"),
    ({"search": "x" * 101}, "search", "String should have at most 100 characters"),
    ({"size": 10}, "size", "Unknown query parameter"),
    ({"sort": "price"}, "sort", "Unknown query parameter"),
    ({"in_stock": "true"}, "in_stock", "Unknown query parameter"),
])
def test_invalid_query_parameters_are_422(client, params, field, message):
    assert errors(client.get("/api/products/", params=params)) == {field: message}


def test_several_invalid_parameters_are_reported_together(client):
    found = errors(client.get("/api/products/", params={"page": 0, "page_size": 500, "sort_by": "sku"}))
    assert set(found) == {"page", "page_size", "sort_by"}


def test_invalid_query_needs_no_token_and_reveals_nothing(client, auth_as):
    auth_as(None)
    response = client.get("/api/products/", params={"sort_by": "password"})
    assert response.status_code == 422
    assert "SELECT" not in response.text and "products." not in response.text


# --- Database-level filtering and paging ---

@pytest.fixture
def product_queries(db_engine):
    """Records the SQL sent for the products table while a test runs."""
    statements: list[tuple[str, object]] = []

    def record(_conn, _cursor, statement, parameters, _context, _many):
        if "FROM products" in statement and statement.lstrip().upper().startswith("SELECT"):
            statements.append((" ".join(statement.split()), parameters))

    event.listen(db_engine, "before_cursor_execute", record)
    yield statements
    event.remove(db_engine, "before_cursor_execute", record)


def test_filtering_and_paging_happen_in_the_database(client, catalogue, product_queries):
    response = client.get("/api/products/", params={
        "search": "mobile", "category_id": catalogue["categories"]["phones"]["id"], "min_price": "1000",
        "max_price": "5000", "availability": "in_stock", "page": 1, "page_size": 2,
        "sort_by": "price", "sort_order": "desc",
    })
    assert response.status_code == 200
    assert len(product_queries) == 2, product_queries  # one COUNT, one page of rows; nothing else
    (count_sql, _), (page_sql, page_params) = product_queries
    assert "count(" in count_sql.lower()
    assert "LIMIT" not in count_sql
    for sql in (count_sql, page_sql):
        # Search, category, both prices, stock and both visibility rules are all in the WHERE clause.
        where = sql.split(" WHERE ", 1)[1]
        for column in ("lower(products.name)", "lower(products.sku)", "products.category_id",
                       "products.price >=", "products.price <=", "products.stock_quantity >",
                       "products.is_active", "categories.is_active"):
            assert column in where, (column, sql)
    assert "ORDER BY products.price DESC, products.id DESC" in page_sql
    assert "LIMIT" in page_sql
    assert 2 in (page_params.values() if isinstance(page_params, dict) else page_params)
    # The sort column is never taken from the request text.
    assert "desc" not in str(page_params).lower()


def test_only_one_page_of_rows_is_fetched(client, make_product, product_queries):
    for _ in range(12):
        make_product()
    product_queries.clear()
    body = client.get("/api/products/", params={"page_size": 5, "page": 2}).json()
    assert (len(body["items"]), body["total"]) == (5, 12)
    page_sql = product_queries[-1][0]
    # SQLite: "LIMIT ? OFFSET ?"; MySQL: "LIMIT %(param_1)s, %(param_2)s" (offset, row count).
    assert re.search(r"LIMIT \S+(,| OFFSET) \S+$", page_sql), page_sql
