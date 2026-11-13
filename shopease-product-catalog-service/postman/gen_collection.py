"""Generate the Postman collection and environment template for the Catalog Service.

    python postman/gen_collection.py

Writes, next to this file:
  ShopEase_Product_Catalog_Service.postman_collection.json    the 20 mandatory scenarios (Task 11)
  ShopEase_Product_Catalog_Service.postman_environment.json   template: no token or secret in it

Using it in Postman: import both files, select the environment, and set admin_token and
customer_token to access tokens of an ADMIN and a USER account of the Authentication Service
(POST http://127.0.0.1:8001/api/auth/login). Then run the folders in order. Folder 20b is meant
to be run many times at once (see scripts/run_postman_suite.py); in a normal sequential run, run
20a, then 20b a few times, and skip 20c's exact counts.

Every request has tests (pm.test). Every name, SKU and category made by a run includes run_id,
set once per environment by the collection's pre-request script, so runs never collide.
"""

import json
import secrets
from pathlib import Path

from jose import jwt

HERE = Path(__file__).parent
COLLECTION = HERE / "ShopEase_Product_Catalog_Service.postman_collection.json"
ENVIRONMENT = HERE / "ShopEase_Product_Catalog_Service.postman_environment.json"

# Well-formed HS256 token signed with a random key that is thrown away: no Authentication Service
# accepts it. Not a secret. The expiry is far ahead, so it is refused for its signature only.
FORGED_TOKEN = jwt.encode({"sub": "1", "role": "ADMIN", "iat": 1_700_000_000, "exp": 4_100_000_000},
                          secrets.token_urlsafe(32), algorithm="HS256")
P = "PM{{run_id}}"  # prefix of every name and SKU of a run


def request(name, method, path, *, body=None, auth="admin", query=None, tests=(), pre=()):
    """auth: "admin", "customer", "none", "forged", "malformed"."""
    raw = "{{base_url}}" + path
    segments = [p for p in path.split("/") if p]
    if path.endswith("/"):
        segments.append("")  # Postman keeps a trailing slash as an empty last segment
    url = {"raw": raw, "host": ["{{base_url}}"], "path": segments}
    if query:
        url["query"] = [{"key": k, "value": str(v)} for k, v in query.items()]
        url["raw"] += "?" + "&".join(f"{k}={v}" for k, v in query.items())
    item = {"name": name, "request": {"method": method, "header": [], "url": url}}
    token = {"admin": "{{admin_token}}", "customer": "{{customer_token}}", "forged": "{{forged_token}}",
             "malformed": "not-a-jwt"}.get(auth)
    item["request"]["auth"] = ({"type": "bearer", "bearer": [{"key": "token", "value": token, "type": "string"}]}
                               if token else {"type": "noauth"})
    if body is not None:
        item["request"]["header"].append({"key": "Content-Type", "value": "application/json"})
        raw_body = body if isinstance(body, str) else json.dumps(body, indent=2)
        item["request"]["body"] = {"mode": "raw", "raw": raw_body}
    events = []
    if pre:
        events.append({"listen": "prerequest", "script": {"type": "text/javascript", "exec": list(pre)}})
    if tests:
        events.append({"listen": "test", "script": {"type": "text/javascript", "exec": list(tests)}})
    if events:
        item["event"] = events
    return item


def status(code: int) -> str:
    return f"pm.test('status {code}', () => pm.response.to.have.status({code}));"


def detail(text: str) -> str:
    return f"pm.test('detail: {text}', () => pm.expect(pm.response.json().detail).to.eql({json.dumps(text)}));"


def field_error(field: str, message: str | None = None) -> str:
    check = (f"pm.expect(e.map(x => x.message)).to.include({json.dumps(message)});" if message else "")
    return (f"pm.test('error on {field}', () => {{ const e = pm.response.json().errors.filter(x => x.field === "
            f"'{field}'); pm.expect(e.length).to.be.above(0); {check} }});")


def save(variable: str, expression: str = "pm.response.json().id") -> str:
    return f"if (pm.response.code < 300) pm.environment.set('{variable}', {expression});"


def skus(expected: list[str]) -> str:
    wanted = "[" + ", ".join(f"'PM' + pm.environment.get('run_id') + '-{s}'" for s in expected) + "]"
    return (f"pm.test('SKUs in order: {', '.join(expected) or 'none'}', () => pm.expect(pm.response.json().items"
            f".map(p => p.sku)).to.eql({wanted}));")


REPLAY = """const rows = pm.response.json().items.slice().reverse();
let level = 0, broken = [];
rows.forEach(r => { const s = r.transaction_type === 'IN' ? 1 : -1;
  if (r.previous_stock !== level || r.updated_stock !== level + s * r.quantity || r.updated_stock < 0) broken.push(r.id);
  level = r.updated_stock; });
pm.test('history replays without a gap: ' + rows.map(r => r.updated_stock).join(' > '), () => pm.expect(broken).to.eql([]));"""

product = lambda sku, name, price, stock, category="{{category_id}}", **extra: {  # noqa: E731
    "category_id": category, "name": f"{P} {name}", "sku": f"{P}-{sku}", "price": price, "initial_stock": stock,
    **extra}

folders = [
    ("00 Setup", [
        request("Health", "GET", "/health", auth="none", tests=[status(200)]),
        request("Database health", "GET", "/health/db", auth="none", tests=[status(200)]),
        request("Create category Phones", "POST", "/api/categories/", body={"name": f"{P} Phones"},
                tests=[status(201), save("category_id")]),
        request("Create category Laptops", "POST", "/api/categories/", body={"name": f"{P} Laptops"},
                tests=[status(201), save("laptop_category_id")]),
        request("Create category Archive", "POST", "/api/categories/", body={"name": f"{P} Archive"},
                tests=[status(201), save("archive_category_id")]),
        request("Deactivate category Archive", "PATCH", "/api/categories/{{archive_category_id}}",
                body={"is_active": False}, tests=[status(200)]),
    ]),
    ("01 Create a product with valid information", [
        request("Create product", "POST", "/api/products/",
                body=product("mob-1", "Galaxy Mobile", "1499.5", 7, discount_price="1299.00", brand="Galaxy"),
                tests=[status(201), save("product_id"),
                       "const p = pm.response.json();",
                       "pm.test('SKU stored upper-case', () => pm.expect(p.sku).to.eql('PM' + pm.environment.get('run_id') + '-MOB-1'));",
                       "pm.test('prices as two-place decimals', () => { pm.expect(p.price).to.eql('1499.50'); pm.expect(p.effective_price).to.eql('1299.00'); });",
                       "pm.test('stock 7, active, in its category', () => { pm.expect(p.stock_quantity).to.eql(7); pm.expect(p.is_active).to.be.true; pm.expect(p.category_id).to.eql(Number(pm.environment.get('category_id'))); });"]),
        request("Initial stock was recorded as an IN transaction", "GET", "/api/inventory/{{product_id}}/history",
                tests=[status(200), "const h = pm.response.json();",
                       "pm.test('one IN 7 from 0, remarks Initial stock', () => { pm.expect(h.total).to.eql(1); const t = h.items[0]; pm.expect([t.transaction_type, t.quantity, t.previous_stock, t.updated_stock, t.remarks]).to.eql(['IN', 7, 0, 7, 'Initial stock']); });"]),
    ]),
    ("02 Create a product with a duplicate SKU", [
        request("Same SKU", "POST", "/api/products/", body=product("MOB-1", "Copy", "1.00", 0),
                tests=[status(409), detail("A product with this SKU already exists")]),
        request("Same SKU, other letter case", "POST", "/api/products/",
                body={"category_id": "{{category_id}}", "name": "Copy", "sku": "pm{{run_id}}-mob-1", "price": "1.00"},
                tests=[status(409), detail("A product with this SKU already exists")]),
    ]),
    ("03 Create a product with an invalid category", [
        request("Category does not exist", "POST", "/api/products/",
                body=product("BAD-CAT-1", "Orphan", "1.00", 0, category=999999),
                tests=[status(422), field_error("category_id", "category_id does not refer to an existing category")]),
        request("Category is inactive", "POST", "/api/products/",
                body=product("BAD-CAT-2", "Orphan", "1.00", 0, category="{{archive_category_id}}"),
                tests=[status(422), field_error("category_id", "category_id refers to an inactive category")]),
        request("Category ID not a number", "POST", "/api/products/",
                body=product("BAD-CAT-3", "Orphan", "1.00", 0, category="abc"),
                tests=[status(422), field_error("category_id")]),
    ]),
    ("04 Create a product with a negative price", [
        request("Negative price", "POST", "/api/products/", body=product("NEG-1", "Negative", "-0.01", 0),
                tests=[status(422), field_error("price", "Input should be greater than or equal to 0")]),
        request("Negative discount price", "POST", "/api/products/",
                body=product("NEG-2", "Negative", "10.00", 0, discount_price="-1.00"),
                tests=[status(422), field_error("discount_price", "Input should be greater than or equal to 0")]),
    ]),
    ("05 Retrieve all active products", [
        request("Setup: product to be hidden", "POST", "/api/products/",
                body=product("HIDDEN", "Retired Mobile", "999.00", 1), tests=[status(201), save("hidden_id")]),
        request("Setup: deactivate it", "DELETE", "/api/products/{{hidden_id}}", tests=[status(200)]),
        request("List products, anonymous", "GET", "/api/products/", auth="none",
                query={"category_id": "{{category_id}}"},
                tests=[status(200), "const b = pm.response.json(); const ids = b.items.map(p => p.id);",
                       "pm.test('only active products', () => pm.expect(b.items.every(p => p.is_active)).to.be.true);",
                       "pm.test('includes the new product', () => pm.expect(ids).to.include(Number(pm.environment.get('product_id'))));",
                       "pm.test('leaves out the deactivated one', () => pm.expect(ids).to.not.include(Number(pm.environment.get('hidden_id'))));",
                       "pm.test('paging fields', () => pm.expect(b).to.have.all.keys('items', 'total', 'page', 'page_size', 'total_pages'));"]),
        request("Products of an inactive category are hidden", "GET", "/api/products/", auth="none",
                query={"category_id": "{{archive_category_id}}"},
                tests=[status(200), "pm.test('empty', () => pm.expect(pm.response.json().total).to.eql(0));"]),
        request("Admin with include_inactive also sees it", "GET", "/api/products/",
                query={"category_id": "{{category_id}}", "include_inactive": "true"},
                tests=[status(200), "pm.test('includes the deactivated product', () => pm.expect(pm.response.json().items.map(p => p.id)).to.include(Number(pm.environment.get('hidden_id'))));"]),
    ]),
    ("06 Retrieve product details using an invalid ID", [
        request("ID not a number", "GET", "/api/products/abc", auth="none", tests=[status(422), field_error("product_id")]),
        request("ID 0", "GET", "/api/products/0", auth="none", tests=[status(422), field_error("product_id")]),
        request("ID above the database range", "GET", "/api/products/2147483648", auth="none",
                tests=[status(422), field_error("product_id")]),
        request("ID that does not exist", "GET", "/api/products/999999", auth="none",
                tests=[status(404), detail("Product not found")]),
    ]),
    ("07 Update a product", [
        request("Replace product (PUT)", "PUT", "/api/products/{{product_id}}",
                body={"category_id": "{{category_id}}", "name": f"{P} Galaxy Mobile", "description": "2026 model",
                      "sku": f"{P}-MOB-1", "price": "1500.00", "discount_price": None, "image_url": None,
                      "brand": "Galaxy", "is_active": True},
                tests=[status(200), "const p = pm.response.json();",
                       "pm.test('fields replaced, stock unchanged', () => { pm.expect(p.description).to.eql('2026 model'); pm.expect(p.price).to.eql('1500.00'); pm.expect(p.discount_price).to.eql(null); pm.expect(p.stock_quantity).to.eql(7); });"]),
        request("PUT without every field", "PUT", "/api/products/{{product_id}}", body={"name": "Only a name"},
                tests=[status(422), field_error("sku"), field_error("price")]),
        request("PUT a missing product", "PUT", "/api/products/999999",
                body={"category_id": "{{category_id}}", "name": "X", "description": None, "sku": f"{P}-X",
                      "price": "1.00", "discount_price": None, "image_url": None, "brand": None, "is_active": True},
                tests=[status(404)]),
    ]),
    ("08 Partially update a product", [
        request("Change the price only (PATCH)", "PATCH", "/api/products/{{product_id}}", body={"price": "1450.00"},
                tests=[status(200), "const p = pm.response.json();",
                       "pm.test('price changed, the rest kept', () => { pm.expect(p.price).to.eql('1450.00'); pm.expect(p.description).to.eql('2026 model'); pm.expect(p.stock_quantity).to.eql(7); });"]),
        request("stock_quantity cannot be patched", "PATCH", "/api/products/{{product_id}}",
                body={"stock_quantity": 999}, tests=[status(422), field_error("stock_quantity")]),
        request("Discount not below price", "PATCH", "/api/products/{{product_id}}",
                body={"discount_price": "1450.00"},
                tests=[status(422), field_error("discount_price", "discount_price must be lower than price")]),
    ]),
    ("09 Delete or deactivate a product", [
        request("Setup: product to delete", "POST", "/api/products/", body=product("DEL-1", "To Delete", "5.00", 2),
                tests=[status(201), save("delete_id")]),
        request("Delete (deactivate)", "DELETE", "/api/products/{{delete_id}}",
                tests=[status(200), "pm.test('message', () => pm.expect(pm.response.json().message).to.eql('Product deactivated'));"]),
        request("Customers no longer see it", "GET", "/api/products/{{delete_id}}", auth="none",
                tests=[status(404)]),
        request("The record is kept, inactive", "GET", "/api/products/{{delete_id}}", query={"include_inactive": "true"},
                tests=[status(200), "pm.test('is_active false', () => pm.expect(pm.response.json().is_active).to.be.false);"]),
        request("Its stock history is kept", "GET", "/api/inventory/{{delete_id}}/history",
                tests=[status(200), "pm.test('1 transaction', () => pm.expect(pm.response.json().total).to.eql(1));"]),
        request("Delete a missing product", "DELETE", "/api/products/999999", tests=[status(404)]),
    ]),
    ("10 Create a duplicate category", [
        request("Same name, other letter case", "POST", "/api/categories/", body={"name": "pm{{run_id}} PHONES"},
                tests=[status(409), detail("A category with this name already exists")]),
        request("Same name with extra spaces", "POST", "/api/categories/", body={"name": f"  {P}   Phones "},
                tests=[status(409), detail("A category with this name already exists")]),
    ]),
    ("11 Search and filter products", [
        request("Setup: Budget Phone 800, stock 12", "POST", "/api/products/",
                body=product("PHN-1", "Budget Phone", "800.00", 12), tests=[status(201)]),
        request("Setup: Pixel Mobile 4500, stock 0", "POST", "/api/products/",
                body=product("MOB-2", "Pixel Mobile", "4500.00", 0), tests=[status(201)]),
        request("Setup: Ultrabook 5000, stock 7 (Laptops)", "POST", "/api/products/",
                body=product("LAP-1", "Ultrabook", "5000.00", 7, category="{{laptop_category_id}}"),
                tests=[status(201)]),
        request("search=mobile in Phones", "GET", "/api/products/", auth="none",
                query={"search": "mobile", "category_id": "{{category_id}}"},
                tests=[status(200), skus(["MOB-1", "MOB-2"])]),
        request("search by SKU part", "GET", "/api/products/", auth="none", query={"search": "pm{{run_id}}-lap"},
                tests=[status(200), skus(["LAP-1"])]),
        request("category_id=Laptops", "GET", "/api/products/", auth="none",
                query={"category_id": "{{laptop_category_id}}"}, tests=[status(200), skus(["LAP-1"])]),
        request("min_price=1000&max_price=5000", "GET", "/api/products/", auth="none",
                query={"search": P, "min_price": "1000", "max_price": "5000"},
                tests=[status(200), skus(["MOB-1", "MOB-2", "LAP-1"])]),
        request("availability=out_of_stock", "GET", "/api/products/", auth="none",
                query={"search": P, "availability": "out_of_stock"}, tests=[status(200), skus(["MOB-2"])]),
        request("Combined: mobile, Phones, in stock", "GET", "/api/products/", auth="none",
                query={"search": "mobile", "category_id": "{{category_id}}", "availability": "in_stock"},
                tests=[status(200), skus(["MOB-1"])]),
        request("max_price below min_price", "GET", "/api/products/", auth="none",
                query={"min_price": "50", "max_price": "10"},
                tests=[status(422), field_error("max_price", "max_price must not be lower than min_price")]),
    ]),
    ("12 Test pagination and sorting", [
        request("Page 1, 2 per page, by price", "GET", "/api/products/", auth="none",
                query={"search": P, "page": 1, "page_size": 2, "sort_by": "price", "sort_order": "asc"},
                tests=[status(200), skus(["PHN-1", "MOB-1"]),
                       "const b = pm.response.json(); pm.test('total 4, 2 pages', () => pm.expect([b.total, b.page, b.page_size, b.total_pages]).to.eql([4, 1, 2, 2]));"]),
        request("Page 2", "GET", "/api/products/", auth="none",
                query={"search": P, "page": 2, "page_size": 2, "sort_by": "price", "sort_order": "asc"},
                tests=[status(200), skus(["MOB-2", "LAP-1"])]),
        request("Price descending", "GET", "/api/products/", auth="none",
                query={"search": P, "sort_by": "price", "sort_order": "desc"},
                tests=[status(200), skus(["LAP-1", "MOB-2", "MOB-1", "PHN-1"])]),
        request("Name ascending (default)", "GET", "/api/products/", auth="none", query={"search": P},
                tests=[status(200), skus(["PHN-1", "MOB-1", "MOB-2", "LAP-1"])]),
        request("Page past the end", "GET", "/api/products/", auth="none", query={"search": P, "page": 9},
                tests=[status(200), "pm.test('no items, total 4', () => { pm.expect(pm.response.json().items).to.eql([]); pm.expect(pm.response.json().total).to.eql(4); });"]),
        request("page=0", "GET", "/api/products/", auth="none", query={"page": 0},
                tests=[status(422), field_error("page")]),
        request("page_size=101", "GET", "/api/products/", auth="none", query={"page_size": 101},
                tests=[status(422), field_error("page_size")]),
        request("sort_by not allowed", "GET", "/api/products/", auth="none", query={"sort_by": "id"},
                tests=[status(422), field_error("sort_by")]),
    ]),
    ("13 Increase product stock", [
        request("Stock-in 5", "POST", "/api/inventory/{{product_id}}/stock-in",
                body={"quantity": 5, "remarks": "Supplier delivery"},
                tests=[status(201), "const t = pm.response.json().transaction;",
                       "pm.test('IN 5: 7 -> 12', () => pm.expect([t.transaction_type, t.quantity, t.previous_stock, t.updated_stock]).to.eql(['IN', 5, 7, 12]));"]),
        request("Current stock is 12", "GET", "/api/inventory/{{product_id}}",
                tests=[status(200), "pm.test('12', () => pm.expect(pm.response.json().stock_quantity).to.eql(12));"]),
    ]),
    ("14 Decrease product stock", [
        request("Stock-out 4", "POST", "/api/inventory/{{product_id}}/stock-out", body={"quantity": 4, "remarks": "Order 1001"},
                tests=[status(201), "const t = pm.response.json().transaction;",
                       "pm.test('OUT 4: 12 -> 8', () => pm.expect([t.transaction_type, t.quantity, t.previous_stock, t.updated_stock]).to.eql(['OUT', 4, 12, 8]));"]),
    ]),
    ("15 Attempt to reduce stock below zero", [
        request("Stock-out 9 with 8 available", "POST", "/api/inventory/{{product_id}}/stock-out", body={"quantity": 9},
                tests=[status(409), detail("Insufficient stock: 8 available, 9 requested")]),
        request("Stock is still 8", "GET", "/api/inventory/{{product_id}}",
                tests=[status(200), "pm.test('8', () => pm.expect(pm.response.json().stock_quantity).to.eql(8));"]),
        request("Quantity 0", "POST", "/api/inventory/{{product_id}}/stock-out", body={"quantity": 0},
                tests=[status(422), field_error("quantity")]),
        request("Negative quantity", "POST", "/api/inventory/{{product_id}}/stock-out", body={"quantity": -1},
                tests=[status(422), field_error("quantity")]),
    ]),
    ("16 Verify inventory transaction history", [
        request("History", "GET", "/api/inventory/{{product_id}}/history",
                tests=[status(200), "const h = pm.response.json();",
                       "pm.test('3 transactions, newest first', () => pm.expect(h.items.map(t => t.transaction_type + ' ' + t.quantity)).to.eql(['OUT 4', 'IN 5', 'IN 7']));",
                       "pm.test('every field', () => pm.expect(h.items[0]).to.have.all.keys('id', 'product_id', 'transaction_type', 'quantity', 'previous_stock', 'updated_stock', 'remarks', 'created_at'));",
                       REPLAY]),
    ]),
    ("17 Retrieve low-stock products", [
        request("Stock-out 4: down to 4", "POST", "/api/inventory/{{product_id}}/stock-out", body={"quantity": 4},
                tests=[status(201), "pm.test('is_low_stock', () => pm.expect(pm.response.json().stock.is_low_stock).to.be.true);"]),
        request("Low-stock report", "GET", "/api/inventory/low-stock",
                tests=[status(200), "const r = pm.response.json(); const mine = r.filter(x => x.sku.startsWith('PM' + pm.environment.get('run_id') + '-'));",
                       "pm.test('this run: Pixel (0) and Galaxy (4); not Ultrabook (7) or Budget Phone (12)', () => pm.expect(mine.map(x => x.sku.split('-').slice(1).join('-') + ':' + x.stock_quantity)).to.eql(['MOB-2:0', 'MOB-1:4']));",
                       "pm.test('all at or below the threshold', () => pm.expect(r.every(x => x.is_low_stock && x.stock_quantity <= x.low_stock_threshold)).to.be.true);"]),
    ]),
    ("18 Access administrative APIs as a CUSTOMER", [
        request("Customer can view a product", "GET", "/api/products/{{product_id}}", auth="customer", tests=[status(200)]),
        *[request(f"Customer: {name}", method, path, auth="customer", body=body,
                  tests=[status(403), detail("Admin role required")])
          for name, method, path, body in [
              ("create category", "POST", "/api/categories/", {"name": f"{P} Nope"}),
              ("create product", "POST", "/api/products/", product("NOPE", "Nope", "1.00", 0)),
              ("update product", "PATCH", "/api/products/{{product_id}}", {"price": "0.01"}),
              ("delete product", "DELETE", "/api/products/{{product_id}}", None),
              ("stock-in", "POST", "/api/inventory/{{product_id}}/stock-in", {"quantity": 1}),
              ("stock-out", "POST", "/api/inventory/{{product_id}}/stock-out", {"quantity": 1}),
              ("history", "GET", "/api/inventory/{{product_id}}/history", None),
              ("low-stock report", "GET", "/api/inventory/low-stock", None),
          ]],
        request("Nothing changed", "GET", "/api/inventory/{{product_id}}",
                tests=[status(200), "pm.test('stock still 4', () => pm.expect(pm.response.json().stock_quantity).to.eql(4));"]),
    ]),
    ("19 Access protected APIs without a JWT and with an invalid token", [
        *[request(f"{label}: {name}", method, path, auth=auth, body=body,
                  tests=[status(401), detail("Could not validate credentials"),
                         "pm.test('WWW-Authenticate: Bearer', () => pm.expect(pm.response.headers.get('WWW-Authenticate')).to.eql('Bearer'));"])
          for label, auth in (("No token", "none"), ("Malformed token", "malformed"), ("Forged token", "forged"))
          for name, method, path, body in [
              ("create product", "POST", "/api/products/", {"category_id": 1, "name": "X", "sku": "X-1", "price": "1.00"}),
              ("update product", "PATCH", "/api/products/1", {"price": "0.01"}),
              ("delete product", "DELETE", "/api/products/1", None),
              ("stock-in", "POST", "/api/inventory/1/stock-in", {"quantity": 1}),
              ("history", "GET", "/api/inventory/1/history", None),
              ("low-stock report", "GET", "/api/inventory/low-stock", None),
              ("create category", "POST", "/api/categories/", {"name": "X"}),
          ]],
    ]),
    ("20a Simultaneous stock updates: setup", [
        request("Product with stock 5", "POST", "/api/products/", body=product("CONC", "Concurrency", "1.00", 5),
                tests=[status(201), save("conc_id")]),
    ]),
    ("20b Simultaneous stock updates: one stock-out (run many at once)", [
        request("Stock-out 1", "POST", "/api/inventory/{{conc_id}}/stock-out", body={"quantity": 1},
                tests=["pm.test('201, or 409 Insufficient stock', () => { pm.expect([201, 409]).to.include(pm.response.code); if (pm.response.code === 409) pm.expect(pm.response.json().detail).to.match(/^Insufficient stock: 0 available/); });"]),
    ]),
    ("20c Simultaneous stock updates: verify consistency", [
        request("Stock is 0", "GET", "/api/inventory/{{conc_id}}",
                tests=[status(200), "pm.test('0', () => pm.expect(pm.response.json().stock_quantity).to.eql(0));"]),
        request("History: initial 5 and exactly 5 stock-outs", "GET", "/api/inventory/{{conc_id}}/history",
                query={"page_size": 100},
                tests=[status(200), "const h = pm.response.json();",
                       "pm.test('6 transactions: 1 IN, 5 OUT', () => { pm.expect(h.total).to.eql(6); pm.expect(h.items.filter(t => t.transaction_type === 'OUT').length).to.eql(5); });",
                       REPLAY]),
    ]),
    ("L Live service: public reads", [
        request("Health", "GET", "/health", auth="none", tests=[status(200)]),
        request("Database health", "GET", "/health/db", auth="none", tests=[status(200)]),
        request("List products", "GET", "/api/products/", auth="none",
                tests=[status(200), "const b = pm.response.json();",
                       "pm.test('paging fields', () => pm.expect(b).to.have.all.keys('items', 'total', 'page', 'page_size', 'total_pages'));",
                       "pm.test('only active products', () => pm.expect(b.items.every(p => p.is_active)).to.be.true);"]),
        request("Search, filter, page and sort", "GET", "/api/products/", auth="none",
                query={"search": "mobile", "min_price": "1000", "max_price": "5000", "availability": "in_stock",
                       "page": 1, "page_size": 10, "sort_by": "price", "sort_order": "asc"},
                tests=[status(200), "const b = pm.response.json();",
                       "pm.test('page 1 of size 10', () => pm.expect([b.page, b.page_size]).to.eql([1, 10]));",
                       "pm.test('ascending prices', () => { const p = b.items.map(x => Number(x.price)); pm.expect(p).to.eql(p.slice().sort((a, c) => a - c)); });"]),
        request("List categories", "GET", "/api/categories/", auth="none", tests=[status(200)]),
    ]),
    ("99 Cleanup (deactivate what this run created)", [
        request("Deactivate product", "DELETE", "/api/products/{{product_id}}", tests=[status(200)]),
        request("Deactivate category Phones", "PATCH", "/api/categories/{{category_id}}", body={"is_active": False},
                tests=[status(200)]),
        request("Deactivate category Laptops", "PATCH", "/api/categories/{{laptop_category_id}}",
                body={"is_active": False}, tests=[status(200)]),
    ]),
]

NO_LEAK = ("pm.test('no internal details in the response', () => pm.expect(pm.response.text())"
           ".to.not.match(/Traceback|sqlalchemy|pymysql|IntegrityError|SELECT |INSERT /));")

collection = {
    "info": {
        "name": "ShopEase Product Catalog Service",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        "description": (
            "The 20 mandatory test scenarios of the Product Catalog Service (Task 11), in order. "
            "Set admin_token and customer_token in the environment (ADMIN and USER accounts of the "
            "Authentication Service). Folder L runs against any instance without tokens."),
    },
    "event": [
        {"listen": "prerequest", "script": {"type": "text/javascript", "exec": [
            "if (!pm.environment.get('run_id')) pm.environment.set('run_id', String(Date.now()).slice(-9));"]}},
        {"listen": "test", "script": {"type": "text/javascript", "exec": [NO_LEAK]}},
    ],
    "variable": [{"key": "forged_token", "value": FORGED_TOKEN, "type": "string"}],
    "item": [{"name": name, "item": items} for name, items in folders],
}

environment = {
    "name": "ShopEase Catalog - template (no secrets)",
    "values": [
        {"key": "base_url", "value": "http://127.0.0.1:8006", "enabled": True},
        {"key": "admin_token", "value": "", "type": "secret", "enabled": True},
        {"key": "customer_token", "value": "", "type": "secret", "enabled": True},
        {"key": "run_id", "value": "", "enabled": True},
    ],
}

if __name__ == "__main__":
    COLLECTION.write_text(json.dumps(collection, indent=2) + "\n", encoding="utf-8")
    ENVIRONMENT.write_text(json.dumps(environment, indent=2) + "\n", encoding="utf-8")
    count = sum(len(items) for _, items in folders)
    print(f"Postman files written: {len(folders)} folders, {count} requests.")
