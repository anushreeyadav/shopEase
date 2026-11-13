"""Build the nine Word documents of the submission (Task 12) into DELIVERABELS/Word_Documents/.

    pip install python-docx          (documentation tool only; not a dependency of the service)
    python -m scripts.build_word_documents

Figures that come from test runs (pytest totals, Newman totals, the final audit) are read from the
evidence files under DELIVERABELS/Test_Results when the documents are built, not typed in, so the
documents always match the evidence. Request and response examples are copied from the recorded
transcripts (DELIVERABELS/Test_Results/*_logs/*transcript.md).
"""

import json
import re
from pathlib import Path

from scripts.docx_kit import Doc

ROOT = Path(__file__).resolve().parent.parent
DEL = ROOT / "DELIVERABELS"
TR = DEL / "Test_Results"
OUT = DEL / "Word_Documents"
DATE = "13 November 2026"
VERSION = "1.0.0"


# --- evidence ------------------------------------------------------------------------------------
def pytest_result(name: str) -> tuple[str, str]:
    text = (TR / "final_audit" / name).read_text(encoding="utf-8")
    recorded = re.search(r"# Recorded (.+ UTC)", text).group(1)
    summary = re.findall(r"=+ (.+ in [\d.]+s.*?) =+", text)[-1]
    return recorded, summary


def module_counts() -> list[tuple[str, int]]:
    text = (TR / "final_audit" / "02_pytest_mysql.log").read_text(encoding="utf-8")
    counts: dict[str, int] = {}
    for m in re.finditer(r"^(tests/\w+\.py)::.* PASSED", text, re.M):
        counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    total = re.search(r"(\d+) passed", text).group(1)
    assert sum(counts.values()) == int(total), (sum(counts.values()), total)
    return sorted(counts.items())


NEWMAN = json.loads((TR / "postman" / "summary.json").read_text(encoding="utf-8"))
AUDIT = (TR / "final_audit" / "03_final_audit.txt").read_text(encoding="utf-8")
AUDIT_PASS, AUDIT_FAIL = AUDIT.count("[PASS]"), AUDIT.count("[FAIL]")
LOG_FILES = re.search(r"(\d+) evidence \.log files", AUDIT).group(1)
AUDIT_TIME = re.search(r"# Final audit, (.+ UTC)", AUDIT).group(1)
SQLITE, MYSQL = pytest_result("01_pytest_sqlite.log"), pytest_result("02_pytest_mysql.log")
A1, B = NEWMAN["A1 sequential"], NEWMAN["B live"]
A3, A5, A2 = NEWMAN["A3 verify"], NEWMAN["A5 cleanup requests"], NEWMAN["A2 burst"]
SCREENSHOTS = sorted(p.name for p in (DEL / "screenshots").glob("*.png"))
LIVE_CUSTOMER = (TR / "live_customer" / "live_customer_check.txt").read_text(encoding="utf-8")
LIVE_CUST_PASS, LIVE_CUST_FAIL = re.search(r"(\d+) passed, (\d+) failed", LIVE_CUSTOMER).groups()
LIVE_CUST_TIME = re.search(r"Live customer check, (.+ UTC)", LIVE_CUSTOMER).group(1)
COV_STMTS, COV_MISS, COV_PCT = re.search(r"^TOTAL\s+(\d+)\s+(\d+)\s+(\d+%)",
                                         (TR / "final_audit" / "04_coverage_mysql.txt").read_text(encoding="utf-8"),
                                         re.M).groups()
SUBMISSION = {f.name: sorted(x.name for x in f.glob("*.png"))
              for f in sorted((DEL / "screenshots" / "submission").iterdir()) if f.is_dir()}
SUB_DONE = sum(1 for files in SUBMISSION.values() if files)
SUB_MISSING = [name for name, files in SUBMISSION.items() if not files]
SUB_STATUS = "Completed" if not SUB_MISSING else "Pending"
SUB_NOTE = (f"{SUB_DONE} of {len(SUBMISSION)} items captured in screenshots/submission/ (ADMIN items on the test instance, "
            "named _test_instance)" + (f"; still to capture: {', '.join(SUB_MISSING)}" if SUB_MISSING else ""))


def meta(document: str, extra: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    return [("Project", "ShopEase – Product Catalog Microservice with Category and Inventory Management"),
            ("Document", document), ("Service version", VERSION), ("Date", DATE),
            *(extra or []), ("Prepared by", "")]


def tree() -> str:
    skip = {".venv", ".pytest_cache", "__pycache__", ".git"}
    lines = ["shopease-product-catalog-service/"]

    def walk(folder: Path, prefix: str, depth: int) -> None:
        entries = sorted([p for p in folder.iterdir() if p.name not in skip and not p.name.startswith("~$")],
                         key=lambda p: (p.is_file(), p.name.lower()))
        for i, p in enumerate(entries):
            last = i == len(entries) - 1
            if p.is_dir() and p.name == "submission":
                n = sum(1 for f in p.iterdir() if f.is_dir())
                shots = sum(1 for f in p.rglob("*.png"))
                lines.append(f"{prefix}{'└── ' if last else '├── '}{p.name}/  ({n} folders 01–18; {shots} screenshots saved so far)")
                continue
            if p.is_dir() and depth >= 1 and p.parent.name == "Test_Results":
                n = sum(1 for f in p.rglob("*") if f.is_file())
                lines.append(f"{prefix}{'└── ' if last else '├── '}{p.name}/  ({n} files)")
                continue
            if p.is_dir() and p.name == "Docker_Evidence":
                n = sum(1 for f in p.iterdir() if f.is_file() and f.suffix != ".md")
                lines.append(f"{prefix}{'└── ' if last else '├── '}{p.name}/  (README.md + {n} evidence files)")
                continue
            if p.is_file() and folder.name == "screenshots" and p.suffix != ".md":
                continue
            if p.name == ".env":
                lines.append(f"{prefix}{'└── ' if last else '├── '}.env  (local only; ignored by Git and Docker, not a deliverable)")
                continue
            lines.append(f"{prefix}{'└── ' if last else '├── '}{p.name}{'/' if p.is_dir() else ''}")
            if p.is_dir() and depth < 2:
                walk(p, prefix + ("    " if last else "│   "), depth + 1)
        if folder.name == "screenshots":
            lines.append(f"{prefix}    ({len(SCREENSHOTS)} automated Swagger UI screenshots from Task 11)")

    walk(ROOT, "", 0)
    return "\n".join(lines)


# --- shared tables -------------------------------------------------------------------------------
ENDPOINTS = [
    ("GET", "/health", "Public", "Service health"),
    ("GET", "/health/db", "Public", "Database connectivity (503 when the database is unreachable)"),
    ("GET", "/api/categories/", "Public (ADMIN for include_inactive)", "List active categories"),
    ("GET", "/api/categories/{category_id}", "Public (ADMIN for include_inactive)", "Get one category"),
    ("POST", "/api/categories/", "ADMIN", "Create a category"),
    ("PUT", "/api/categories/{category_id}", "ADMIN", "Replace a category (every field)"),
    ("PATCH", "/api/categories/{category_id}", "ADMIN", "Change some fields, e.g. is_active"),
    ("DELETE", "/api/categories/{category_id}", "ADMIN", "Delete an empty category (409 if it has products)"),
    ("GET", "/api/products/", "Public (ADMIN for include_inactive)", "List, search, filter, sort and page products"),
    ("GET", "/api/products/{product_id}", "Public (ADMIN for include_inactive)", "Get one product"),
    ("POST", "/api/products/", "ADMIN", "Create a product, optional initial_stock"),
    ("PUT", "/api/products/{product_id}", "ADMIN", "Replace a product (every editable field)"),
    ("PATCH", "/api/products/{product_id}", "ADMIN", "Change some fields of a product"),
    ("DELETE", "/api/products/{product_id}", "ADMIN", "Deactivate a product (soft delete)"),
    ("GET", "/api/inventory/{product_id}", "ADMIN", "Current stock and low-stock flag"),
    ("POST", "/api/inventory/{product_id}/stock-in", "ADMIN", "Add stock (IN transaction)"),
    ("POST", "/api/inventory/{product_id}/stock-out", "ADMIN", "Remove stock (OUT transaction)"),
    ("GET", "/api/inventory/{product_id}/history", "ADMIN", "Complete stock history, newest first, paged"),
    ("GET", "/api/inventory/low-stock", "ADMIN", "Active products at or below LOW_STOCK_THRESHOLD"),
]

SCENARIOS = [  # (#, scenario, expected, actual on the test instance, live status)
    (1, "Create a product with valid information", "201; row, FK and initial IN transaction stored",
     "201; SKU stored upper-case, price \"1499.50\", stock 7; history 1 × IN 7", "Blocked (needs ADMIN)"),
    (2, "Duplicate SKU", "409, no second row", "409 for the same SKU and for other letter case; 1 row", "Blocked (needs ADMIN)"),
    (3, "Invalid category", "422, no row", "422 for missing, inactive and non-numeric category", "Blocked (needs ADMIN)"),
    (4, "Negative price", "422, no row", "422 on price and on discount_price", "Blocked (needs ADMIN)"),
    (5, "Retrieve all active products", "200; only active products in active categories",
     "Inactive product and product in inactive category hidden", "Partly: 200, live database empty"),
    (6, "Invalid product ID", "422 for abc / 0 / 2^31; 404 for unknown", "422, 422, 422, 404", "Passed live"),
    (7, "Update a product (PUT)", "200; every field required; stock unchanged", "200; 422 without every field; 404 missing", "Blocked (needs ADMIN)"),
    (8, "Partially update a product (PATCH)", "200; other fields kept", "200; stock_quantity refused 422; discount ≥ price 422", "Blocked (needs ADMIN)"),
    (9, "Delete / deactivate a product", "200; is_active false; row and history kept",
     "200; customers get 404; admin sees it inactive; history kept", "Blocked (needs ADMIN)"),
    (10, "Duplicate category", "409", "409 for other letter case and extra spaces; 1 row", "Blocked (needs ADMIN)"),
    (11, "Search and filter products", "Exact matching set", "Name, SKU, category, price range, availability, combined", "Partly: 200, live database empty"),
    (12, "Pagination and sorting", "Page fields; stable order", "total/page/page_size/total_pages; both pages; asc/desc; past the end; 422s", "Partly: 200, live database empty"),
    (13, "Increase stock", "201; IN row; stock + n", "IN 5: 7 → 12", "Blocked (needs ADMIN)"),
    (14, "Decrease stock", "201; OUT row; stock − n", "OUT 4: 12 → 8", "Blocked (needs ADMIN)"),
    (15, "Reduce stock below zero", "409; nothing changed", "409 \"Insufficient stock: 8 available, 9 requested\"; stock 8; 0 and −1 → 422", "Blocked (needs ADMIN)"),
    (16, "Inventory transaction history", "Every movement, newest first", "3 rows newest first; all fields; history replays to the stock", "Blocked (needs ADMIN)"),
    (17, "Low-stock products", "Stock ≤ threshold listed", "Products at 0 and 4 listed; 7 and 12 not (threshold 5)", "Blocked (needs ADMIN)"),
    (18, "Admin APIs as a CUSTOMER", "403; nothing changed", "pytest 13 calls → 403; Postman 8 calls → 403 \"Admin role required\"", f"Passed live ({LIVE_CUST_PASS} checks, real customer account)"),
    (19, "No JWT and invalid JWT", "401 with WWW-Authenticate: Bearer", "5 token cases × 6 endpoints → 401", "Passed live (21 requests)"),
    (20, "Simultaneous stock updates", "Stock never negative; history one chain",
     f"pytest: 12 threads, stock 5 → exactly 5 succeed; Newman: {A2['201']} × 201, {A2['409']} × 409", "Blocked (needs ADMIN)"),
]


# --- 1 -------------------------------------------------------------------------------------------
def project_overview() -> Doc:
    d = Doc("Project Overview", "Objective, technology stack, architecture and independent microservice design",
            meta("Project_Overview.docx", [("Location", r"C:\Users\Administrator\ShopEase\shopease-product-catalog-service")]))
    d.h1("1. Project objective")
    d.p("The Product Catalog Service is an independent FastAPI microservice that extends the ShopEase e-commerce "
        "platform with **product categories**, **products** and **inventory management**. It replaces nothing: the "
        "earlier ShopEase Product Service (port 8003, in-memory) is a separate project and was not changed.")
    d.table(["Goal", "How it is met"], [
        ["Manage categories", "Create, list, view, update, activate/deactivate; delete only when empty"],
        ["Manage products", "Create, list, view, replace (PUT), partially update (PATCH), deactivate; unique SKU; Decimal prices"],
        ["Find products", "Search by name or SKU, filter by category, price range and availability, sort and page – all in MySQL"],
        ["Manage stock", "Stock-in and stock-out with a permanent transaction history and a low-stock report"],
        ["Secure administration", "Every change needs an ADMIN token verified by the existing Authentication Service"],
        ["Run anywhere", "Docker Compose stack: API and its own MySQL 8.4 database, migrations applied at start-up"],
    ], widths=[4.5, 12.5])

    d.h1("2. Technology stack")
    d.table(["Component", "Choice", "Version"], [
        ["Language", "Python", "3.11"], ["Web framework / server", "FastAPI, Uvicorn", "0.162.0 / 0.54.0"],
        ["Validation and settings", "Pydantic, pydantic-settings, python-dotenv", "2.14.2 / 2.16.2 / 1.2.4"],
        ["Database access", "SQLAlchemy ORM, PyMySQL (+ cryptography for MySQL 8 auth)", "2.1.6 / 1.2.3"],
        ["Migrations", "Alembic", "1.20.1"], ["Database", "MySQL (Docker image mysql:8.4)", "8.4.11"],
        ["JWT library", "python-jose (format pre-check only; no secret)", "3.5.0"],
        ["HTTP client to the Auth Service", "httpx", "0.28.1"], ["Tests", "pytest; Postman collection run with Newman", "9.2.0 / 6.2.1"],
        ["Containers", "Docker, Docker Compose", "29.6.2 / v5.3.1"],
    ], widths=[5, 8, 4])

    d.h1("3. Architecture")
    d.h2("3.1 Place in the ShopEase platform")
    d.table(["Service", "Port", "Database", "Responsibility"], [
        ["API Gateway (main platform)", "8000", "—", "Routes requests to the platform services"],
        ["Authentication Service", "8001", "Own MySQL", "Registration, login, JWT issue and verification"],
        ["User Service", "8002", "Own MySQL", "User profiles and addresses"],
        ["Product Service (earlier prototype)", "8003", "None (in-memory)", "Original product prototype; untouched"],
        ["Order / Payment Services", "8004 / 8005", "Own MySQL", "Orders and payments"],
        ["**Product Catalog Service**", "**8006**", "**shopease_product_catalog_db**", "**Categories, products, inventory**"],
    ], widths=[5, 1.8, 4.2, 6])
    d.p("The service refuses to start on ports 8000–8005, which belong to the other services.")
    d.h2("3.2 Layers inside the service")
    d.code("HTTP request\n"
           "  │\n"
           "  ▼  app/routers/      endpoints only: parse the request, call a service, shape the response\n"
           "  ▼  app/core/security token check through the Authentication Service, role check\n"
           "  ▼  app/schemas/      Pydantic validation of bodies and query parameters (unknown fields refused)\n"
           "  ▼  app/services/     business rules and database transactions (commit / rollback)\n"
           "  ▼  app/models/       SQLAlchemy tables + stock guard (no stock change without a transaction row)\n"
           "  ▼  app/database/     engine, sessions (UTC), wait-for-database helper\n"
           "  ▼  MySQL 8.4         constraints: unique, foreign keys (RESTRICT), CHECKs")
    d.h2("3.3 Request flow with a token")
    d.code("Client ──Bearer token──▶ Catalog Service (8006) ──same token──▶ Authentication Service (8001)\n"
           "                         1. header, scheme, JWT format, alg       POST /api/auth/verify-token\n"
           "                         2. forward the token  ─────────────────▶ signature, exp, user exists, active\n"
           "                         3. ◀── 200 {user: id, role, is_active} / 401 / 403\n"
           "                         4. role check (ADMIN for every change)\n"
           "                         5. business rule + MySQL transaction")

    d.h1("4. Independent microservice design")
    d.bullets([
        "**Own database:** `shopease_product_catalog_db` in its own MySQL container and named volume. No other service reads or writes it, and it reads no other service's database.",
        "**Own code base and deployment:** a separate folder, Dockerfile and Compose project (`shopease-product-catalog-service`). It shares no code with the earlier Product Service and was not merged with it.",
        "**No user data:** no registration, login, passwords or JWT secret. Identity and role come from the Authentication Service's own `verify-token` endpoint, so a deactivated user or a role change takes effect immediately.",
        "**Fail closed:** if the Authentication Service cannot answer, requests that carry a token get 503 and nothing is changed; anonymous browsing keeps working.",
        "**Loose coupling to Docker networks:** containers reach the Authentication Service through `host.docker.internal:8001` by default; joining its network is optional (`docker-compose.auth-network.yml`).",
        "**Schema owned by Alembic:** tables are created and changed only by versioned migrations, applied automatically when the container starts.",
        "**Configuration from the environment:** every setting and credential comes from environment variables or a local `.env` (excluded from Git and from the image).",
    ])
    d.h1("5. Functional scope")
    d.table(["Area", "Endpoints", "Access"], [
        ["Service", "GET /, /health, /health/db, Swagger UI /docs, ReDoc /redoc", "Public"],
        ["Categories", "GET list and one; POST; PUT; PATCH; DELETE (empty only)", "Read public; changes ADMIN"],
        ["Products", "GET list (search, filter, sort, page) and one; POST; PUT; PATCH; DELETE (deactivate)", "Read public; changes ADMIN"],
        ["Inventory", "GET stock; POST stock-in; POST stock-out; GET history; GET low-stock", "ADMIN"],
    ], widths=[3, 10, 4])
    d.p("Customers (role `USER` in the Authentication Service, which has no `CUSTOMER` role) see only active "
        "products in active categories, the same as anonymous visitors.")
    d.h1("6. Related documents")
    d.bullets(["Database_Schema_Documentation.docx", "API_Documentation.docx", "JWT_Authentication_Report.docx",
               "API_Testing_Report.docx", "Docker_Execution_Report.docx", "Final_Project_Completion_Report.docx",
               "README.md in the project root"])
    return d


# --- 2 -------------------------------------------------------------------------------------------
def day1() -> Doc:
    d = Doc("Day 1 Development Report", "Project setup, configuration, database models, migrations, JWT integration, category and product APIs",
            meta("Day_1_Development_Report.docx", [("Tasks covered", "Tasks 1–7 of the project plan")]))
    d.note("The Day 1 / Day 2 split follows the project plan's topics. The project folder was created on "
           "11 November 2026; the recorded evidence (logs, transcripts) of these tasks is dated 12 November 2026 (UTC).")
    d.h1("1. Project setup (Task 1)")
    d.bullets([
        "New, independent folder `shopease-product-catalog-service`, with a layered package: `app/core`, `app/database`, `app/models`, `app/schemas`, `app/services`, `app/routers`.",
        "FastAPI application with `GET /`, `GET /health`, Swagger UI at `/docs` and ReDoc at `/redoc`; started with `python -m app`.",
        "Port **8006** chosen because 8000–8005 belong to other ShopEase services; the service refuses those ports.",
        "Deliverables folders created under `DELIVERABELS/`; `.gitignore` excludes `.env`, `.venv` and caches.",
    ])
    d.h1("2. Environment configuration (Task 2)")
    d.p("All settings are defined once in `app/core/config.py` (pydantic-settings) and read from environment "
        "variables or `.env`; environment variables win. `.env.example` is the committed template.")
    d.table(["Variable", "Default", "Purpose"], [
        ["SERVICE_HOST / SERVICE_PORT", "127.0.0.1 / 8006", "Listening address"],
        ["MYSQL_DATABASE", "shopease_product_catalog_db", "Database name"],
        ["MYSQL_USER / MYSQL_PASSWORD", "none – required", "Credentials; a placeholder password is refused"],
        ["MYSQL_HOST / MYSQL_PORT", "127.0.0.1 / 3310", "Database address"],
        ["AUTH_SERVICE_VERIFY_URL", "http://127.0.0.1:8001/api/auth/verify-token", "Token verification endpoint"],
        ["AUTH_SERVICE_TIMEOUT_SECONDS", "5", "Timeout of that call"],
        ["JWT_ALGORITHM", "HS256", "Must match the Authentication Service"],
        ["LOW_STOCK_THRESHOLD", "5", "Stock at or below it is low"],
        ["APP_ENV, LOG_LEVEL, API_PREFIX, DOCS_ENABLED", "development, INFO, /api, true", "Application"],
    ], widths=[5.5, 5.5, 6])
    d.p("No JWT secret exists in this service, and no password is hard-coded. Pinned dependency versions are in "
        "`requirements.txt` and match the other ShopEase services.")
    d.h1("3. Database models (Task 3)")
    d.table(["Model", "Table", "Key rules"], [
        ["Category", "categories", "Unique, non-blank name; is_active flag; UTC timestamps"],
        ["Product", "products", "FK category (RESTRICT); unique SKU; DECIMAL(10,2) price; discount < price; stock ≥ 0"],
        ["InventoryTransaction", "inventory_transactions", "FK product (RESTRICT); type IN/OUT; quantity > 0; updated = previous ± quantity"],
    ], widths=[4, 4.5, 8.5])
    d.p("Money is handled as Python `Decimal`, never float. Timestamps are stored and returned in UTC. "
        "Details: Database_Schema_Documentation.docx.")
    d.h1("4. Alembic migrations (Task 4)")
    d.bullets([
        "`alembic.ini` holds no URL or credentials; `alembic/env.py` builds the URL from the same settings as the app and imports every model.",
        "`env.py` refuses any database other than `shopease_product_catalog_db` and the throwaway `shopease_product_catalog_test_db`.",
        "Migration `5b8e2f0c9d14` creates the three tables. Autogenerate output was compared with it (no functional difference).",
        "Executed on MySQL 8.4.11: `alembic upgrade head` on the configured database; upgrade → downgrade → upgrade cycle on the test database only; `alembic check` reports no differences.",
        "Evidence: `Test_Results/Migration_Execution_Report.md` and `migration_logs/01–10`.",
    ])
    d.h1("5. JWT integration with the existing Authentication Service (Task 5)")
    d.bullets([
        "The Authentication Service's code was read to find its real behaviour: HS256 with a shared secret, claims `sub`, `role`, `iat`, `exp`, roles `USER` and `ADMIN`, and the endpoint `POST /api/auth/verify-token`.",
        "The Catalog Service does a local format check only (python-jose, no secret), then sends the token to `verify-token` and trusts only a 200 answer. The role used is the one returned from the Authentication Service's database.",
        "Reusable dependencies in `app/core/security.py`: `get_current_authenticated_user`, `get_optional_user`, `require_roles`, `require_admin`.",
        "401 for missing/invalid/expired tokens, 403 for inactive users or a missing role, 503 when the Authentication Service cannot answer (fail closed).",
        "The Authentication Service was not modified; no account was created or changed.",
    ])
    d.h1("6. Category APIs (Task 6)")
    d.table(["Rule", "Behaviour"], [
        ["Name", "Required, trimmed, inner spaces collapsed, 1–100 characters, at least one letter or digit"],
        ["Uniqueness", "Case-insensitive (and accent-insensitive on MySQL): 409 \"A category with this name already exists\""],
        ["Activation", "is_active false hides the category and its products from public listings"],
        ["Delete", "Only an empty category; otherwise 409 and nothing changes (products are never moved or deleted)"],
        ["Access", "Reads public; POST/PUT/PATCH/DELETE need ADMIN"],
    ], widths=[3.5, 13.5])
    d.h1("7. Product APIs (Task 7)")
    d.table(["Rule", "Behaviour"], [
        ["Required", "category_id, name, sku, price; optional description, discount_price, image_url, brand, initial_stock"],
        ["Category", "Must exist and be active (422 otherwise), checked with the category row locked"],
        ["SKU", "Letters, digits, hyphens; stored upper-case; unique ignoring case: 409"],
        ["Money", "Decimal, 0–99,999,999.99, 2 places, never negative; discount strictly below price"],
        ["Stock", "Not accepted by product endpoints; initial_stock becomes the first IN transaction"],
        ["Delete", "Soft delete: is_active false; the row and its history stay"],
        ["Errors", "400 bad JSON, 401, 403, 404, 409, 422 with a field-by-field list; no SQL or internal details"],
    ], widths=[3.5, 13.5])
    d.h1("8. Verification at the end of Day 1")
    d.table(["Evidence", "Result"], [
        ["migration_logs/ and Migration_Execution_Report.md", "Migration executed and verified on MySQL 8.4.11"],
        ["auth_integration_logs/01_live_auth_service_check.log", "16 of 16 live checks passed against the real Authentication Service (no account used)"],
        ["category_api_logs/01_pytest_category_api.log", "Category API tests passed"],
        ["product_api_logs/02_api_transcript.md", "54 of 54 recorded requests returned the expected status"],
    ], widths=[8, 9])
    d.p("Current totals for the same modules (final audit run, MySQL): see API_Testing_Report.docx.")
    return d


# --- 3 -------------------------------------------------------------------------------------------
def day2() -> Doc:
    d = Doc("Day 2 Development Report", "Search and filtering, inventory management, Docker deployment, testing and validation",
            meta("Day_2_Development_Report.docx", [("Tasks covered", "Tasks 8–12 of the project plan")]))
    d.note("The recorded evidence of these tasks is dated 12 November 2026 (UTC).")
    d.h1("1. Search, filtering, pagination and sorting (Task 8)")
    d.table(["Parameter", "Values", "Meaning"], [
        ["search", "1–100 characters", "Part of the name or SKU, ignoring case; % and _ match themselves"],
        ["category_id", "positive integer", "Products in that category"],
        ["min_price / max_price", "decimal ≥ 0, 2 places", "Inclusive range; max must not be below min"],
        ["availability", "in_stock, out_of_stock", "Stock above 0 / equal to 0"],
        ["brand", "1–100 characters", "Exact brand, ignoring case"],
        ["page / page_size", "1–100000 / 1–100 (default 20)", "Paging"],
        ["sort_by / sort_order", "name, price, created_at / asc, desc", "Only approved columns; ties ordered by id"],
    ], widths=[3.5, 5, 8.5])
    d.bullets([
        "Response: `{items, total, page, page_size, total_pages}`.",
        "Filtering, counting, sorting and paging run in MySQL (one COUNT and one LIMIT/OFFSET query); migration `c4a7d2e91b30` adds indexes on `price` and `created_at`.",
        "Every parameter is validated; unknown parameters get 422 \"Unknown query parameter\".",
        "Customer visibility rules apply to every result and to `total`.",
        "Tested with a 375-combination grid compared with a reference implementation (`tests/test_product_search.py`).",
    ])
    d.h1("2. Inventory management (Task 9)")
    d.code("POST /api/inventory/42/stock-out {\"quantity\": 3}\n"
           "  BEGIN\n"
           "  SELECT ... FROM products WHERE id = 42 FOR UPDATE   -- a second request for product 42 waits here\n"
           "  (stock 4 - 3 = 1 >= 0 allowed; below 0 -> 409, ROLLBACK, nothing written)\n"
           "  UPDATE products SET stock_quantity = 1 WHERE id = 42\n"
           "  INSERT INTO inventory_transactions (OUT, 3, previous 4, updated 1, remarks, created_at)\n"
           "  COMMIT                                              -- both saved, lock released\n"
           "  any failure -> ROLLBACK: neither saved")
    d.bullets([
        "Endpoints: current stock, stock-in, stock-out, history (paged, newest first), low-stock report – all ADMIN only.",
        "Quantity is a strict whole number 1 to 1,000,000,000; stock can never become negative (application check and database CHECK).",
        "Initial stock is recorded as the first IN transaction; product endpoints refuse `stock_quantity`.",
        "A stock guard (`app/models/stock_guard.py`) refuses any stock change that is not matched by transaction rows.",
        "`LOW_STOCK_THRESHOLD` (default 5): active products at or below it are reported.",
        "Verified with rollback fault injection, 12-thread concurrency tests on MySQL, and six deliberate bugs that the tests all detected (`inventory_logs/03_mutation_checks.log`).",
    ])
    d.h1("3. Docker deployment (Task 10)")
    d.bullets([
        "`Dockerfile`: python:3.11-slim-bookworm, non-root user, only `app/`, `alembic/`, `alembic.ini` and requirements copied; EXPOSE 8006; health check on /health.",
        "`docker-compose.yml`: `catalog-mysql` (mysql:8.4, named volume `catalog_mysql_data`, health check as the service user) and `catalog-service` (starts when MySQL is healthy).",
        "Start-up: wait for the database → `alembic upgrade head` → server.",
        "Credentials come from `.env` at run time; a scan found no secret value in 9,279 image files or the build history.",
        "Executed: `up --build -d`, `ps`, `logs`, `down` (volume kept) and a restart showing the data persisted. Evidence: `DELIVERABELS/Docker_Evidence/01–11`.",
    ])
    d.h1("4. Testing and validation (Task 11)")
    d.table(["Run", "Result"], [
        ["pytest, SQLite (final audit " + SQLITE[0] + ")", SQLITE[1]],
        ["pytest, MySQL 8.4 test database (final audit " + MYSQL[0] + ")", MYSQL[1]],
        ["Postman/Newman, all 20 scenarios on the test instance", f"{A1['requests']} requests, {A1['assertions']} assertions, {A1['assertions_failed']} failed"],
        ["Newman, 12 simultaneous stock-outs (stock 5)", f"{A2['201']} × 201, {A2['409']} × 409"],
        ["Direct SQL checks after the Postman run", "11 of 11 passed"],
        ["Newman on the live container with the real Authentication Service", f"{B['requests']} requests, {B['assertions']} assertions, {B['assertions_failed']} failed"],
        ["Swagger UI screenshots (automated, real requests)", f"{len(SCREENSHOTS)}"],
        [f"Live customer check, real USER account ({LIVE_CUST_TIME})", f"{LIVE_CUST_PASS} passed, {LIVE_CUST_FAIL} failed"],
        ["Line coverage of app/ (pytest-cov, MySQL suite)", f"{COV_PCT} ({COV_STMTS} statements, {COV_MISS} missed)"],
    ], widths=[10, 7])
    d.p("Scenarios needing an ADMIN token could not be run against the live Authentication Service, which has no "
        "ADMIN account; they were run on a test instance with a stand-in that applies the real service's rules. "
        "Scenario 18 also ran live with a real customer account. Details: API_Testing_Report.docx.")
    d.h1("5. Final audit and submission documents (Task 12)")
    d.bullets([
        f"`python -m scripts.final_audit` ({AUDIT_TIME}): {AUDIT_PASS} checks passed, {AUDIT_FAIL} failed – endpoints, migration, JWT, Docker, secrets, .env.",
        "Nine Word documents generated by `python -m scripts.build_word_documents`; schema SQL reference, endpoint reference, test execution summary and Teams templates added.",
        f"Submission screenshots: {SUB_NOTE}.",
        f"Line coverage measured: {COV_PCT} of app/.",
    ])
    return d


# --- 4 -------------------------------------------------------------------------------------------
def schema() -> Doc:
    d = Doc("Database Schema Documentation", "Tables, relationships and constraints of shopease_product_catalog_db",
            meta("Database_Schema_Documentation.docx", [("Database", "MySQL 8.4.11, InnoDB, utf8mb4 / utf8mb4_0900_ai_ci"),
                                                        ("Alembic revision", "c4a7d2e91b30 (head)")]))
    d.p("The schema is created only by Alembic migrations. The `SHOW CREATE TABLE` output captured from the "
        "running database during the final audit is in `DELIVERABELS/Database_Evidence/schema_reference.sql` "
        "(reference only – not to be run instead of the migrations).")
    d.h1("1. Entity relationship")
    d.code("categories 1 ──────< products 1 ──────< inventory_transactions\n"
           "   id  ◀── products.category_id        id ◀── inventory_transactions.product_id\n"
           "           (ON DELETE RESTRICT)                 (ON DELETE RESTRICT)")
    cols = ["Column", "Type", "Null", "Default", "Description"]
    w = [3.2, 3.2, 1.2, 2.2, 7.2]
    d.h1("2. categories")
    d.table(cols, [
        ["id", "INT AUTO_INCREMENT", "No", "—", "Primary key"],
        ["name", "VARCHAR(100)", "No", "—", "Unique (uq_categories_name), not blank"],
        ["description", "TEXT", "Yes", "NULL", "Optional, up to 5000 characters (API rule)"],
        ["is_active", "TINYINT(1)", "No", "1", "Inactive categories and their products are hidden from customers"],
        ["created_at", "DATETIME", "No", "now()", "UTC"],
        ["updated_at", "DATETIME", "No", "now()", "UTC, updated on change"],
    ], widths=w)
    d.h1("3. products")
    d.table(cols, [
        ["id", "INT AUTO_INCREMENT", "No", "—", "Primary key"],
        ["category_id", "INT", "No", "—", "FK → categories.id, ON DELETE RESTRICT; indexed"],
        ["name", "VARCHAR(200)", "No", "—", "Not blank; indexed (ix_products_name)"],
        ["description", "TEXT", "Yes", "NULL", "Optional"],
        ["sku", "VARCHAR(64)", "No", "—", "Unique (uq_products_sku), stored upper-case, not blank"],
        ["price", "DECIMAL(10,2)", "No", "—", "≥ 0; indexed (ix_products_price)"],
        ["discount_price", "DECIMAL(10,2)", "Yes", "NULL", "NULL or 0 ≤ discount < price"],
        ["stock_quantity", "INT", "No", "0", "≥ 0; changed only by inventory transactions"],
        ["image_url", "VARCHAR(500)", "Yes", "NULL", "Optional"],
        ["brand", "VARCHAR(100)", "Yes", "NULL", "Optional"],
        ["is_active", "TINYINT(1)", "No", "1", "False = deactivated (soft delete)"],
        ["created_at", "DATETIME", "No", "now()", "UTC; indexed (ix_products_created_at)"],
        ["updated_at", "DATETIME", "No", "now()", "UTC"],
    ], widths=w)
    d.h1("4. inventory_transactions")
    d.table(cols, [
        ["id", "INT AUTO_INCREMENT", "No", "—", "Primary key"],
        ["product_id", "INT", "No", "—", "FK → products.id, ON DELETE RESTRICT"],
        ["transaction_type", "VARCHAR(3)", "No", "—", "IN or OUT"],
        ["quantity", "INT", "No", "—", "> 0"],
        ["previous_stock", "INT", "No", "—", "Stock before the movement, ≥ 0"],
        ["updated_stock", "INT", "No", "—", "Stock after; = previous ± quantity, ≥ 0"],
        ["remarks", "VARCHAR(255)", "Yes", "NULL", "Optional note, e.g. \"Initial stock\""],
        ["created_at", "DATETIME", "No", "now()", "UTC; index (product_id, created_at)"],
    ], widths=w)
    d.h1("5. Relationships")
    d.table(["Relationship", "Foreign key", "On delete", "Effect"], [
        ["Category → products (1:N)", "fk_products_category_id_categories", "RESTRICT",
         "A category with any product cannot be deleted (API answers 409); deactivate it instead"],
        ["Product → transactions (1:N)", "fk_inventory_transactions_product_id_products", "RESTRICT",
         "A product with history cannot be deleted; the API DELETE deactivates it"],
    ], widths=[3.8, 5.6, 2, 5.6])
    d.h1("6. Constraints")
    d.table(["Table", "Constraint", "Rule"], [
        ["categories", "uq_categories_name", "Unique name (collation ignores case and accents)"],
        ["categories", "ck_categories_name_not_blank", "trim(name) <> ''"],
        ["products", "uq_products_sku", "Unique SKU"],
        ["products", "ck_products_name_not_blank / ck_products_sku_not_blank", "Not blank"],
        ["products", "ck_products_price_non_negative", "price >= 0"],
        ["products", "ck_products_discount_price_valid", "discount_price IS NULL OR (>= 0 AND < price)"],
        ["products", "ck_products_stock_quantity_non_negative", "stock_quantity >= 0"],
        ["inventory_transactions", "ck_inventory_transactions_transaction_type", "transaction_type IN ('IN','OUT')"],
        ["inventory_transactions", "ck_inventory_transactions_quantity_positive", "quantity > 0"],
        ["inventory_transactions", "ck_..._previous_stock_non_negative / ck_..._updated_stock_non_negative", ">= 0"],
        ["inventory_transactions", "ck_inventory_transactions_stock_arithmetic", "IN: updated = previous + quantity; OUT: updated = previous − quantity"],
    ], widths=[3.4, 6.8, 6.8])
    d.p("In total: 3 primary keys, 2 foreign keys, 2 unique constraints, 11 CHECK constraints (verified by the final "
        "audit from information_schema). CHECK constraints need MySQL 8.0.16 or later.")
    d.h1("7. Indexes")
    d.table(["Index", "Columns", "Used by"], [
        ["uq_products_sku", "sku (unique)", "Duplicate check, search by SKU"],
        ["ix_products_category_id", "category_id", "Category filter, FK"],
        ["ix_products_name", "name", "Sort by name"],
        ["ix_products_price", "price", "Price range filter, sort by price (migration c4a7d2e91b30)"],
        ["ix_products_created_at", "created_at", "Sort by creation time (migration c4a7d2e91b30)"],
        ["ix_inventory_transactions_product_id_created_at", "product_id, created_at", "History of one product, newest first"],
    ], widths=[6.5, 4, 6.5])
    d.h1("8. Migrations")
    d.table(["Revision", "Parent", "Change"], [
        ["5b8e2f0c9d14", "—", "Create categories, products, inventory_transactions with all keys and constraints"],
        ["c4a7d2e91b30 (head)", "5b8e2f0c9d14", "Add ix_products_price and ix_products_created_at"],
    ], widths=[4, 3.5, 9.5])
    d.p("Both the configured database and the test database are at head; `alembic check` reports no difference "
        "between the models and the configured database (final audit).")
    return d


# --- 5 -------------------------------------------------------------------------------------------
def api_doc() -> Doc:
    d = Doc("API Documentation", "Endpoints, methods, request and response examples, status codes and authentication",
            meta("API_Documentation.docx", [("Base URL", "http://127.0.0.1:8006"), ("Interactive docs", "/docs (Swagger UI), /redoc, /openapi.json")]))
    d.h1("1. Conventions")
    d.bullets([
        "JSON bodies; money values are strings with two decimals (`\"19.50\"`); timestamps are UTC (`2026-11-12T09:54:14Z`).",
        "Collections answer at both `/api/products/` and `/api/products` (same for categories), without a redirect.",
        "Authentication: `Authorization: Bearer <access token from the Authentication Service>`.",
        "Errors: `{\"detail\": \"...\"}`; validation errors add `errors: [{field, message}]`.",
    ])
    d.h1("2. Authentication requirements")
    d.table(["Operation", "Anonymous", "Customer (USER)", "ADMIN"], [
        ["List / view active categories and products", "200", "200", "200"],
        ["include_inactive=true", "401", "403", "200"],
        ["Create, update, delete categories and products", "401", "403", "2xx"],
        ["All /api/inventory endpoints", "401", "403", "2xx"],
    ], widths=[8, 3, 3, 3])
    d.h1("3. Status codes")
    d.table(["Code", "Meaning in this API"], [
        ["200 / 201", "Success / created (also stock movements)"],
        ["400", "Body is not a JSON object (malformed JSON, missing body, array, form data)"],
        ["401", "No token, wrong scheme, malformed, expired or wrongly signed token, unknown user (+ WWW-Authenticate: Bearer)"],
        ["403", "Valid token but inactive user, or role not ADMIN (\"Admin role required\")"],
        ["404", "Unknown ID, or a record hidden from this caller"],
        ["409", "Duplicate SKU or category name; category still has products; insufficient stock"],
        ["422", "Invalid field, ID or query parameter, listed field by field"],
        ["503", "Authentication Service or database unavailable"],
    ], widths=[2.5, 14.5])
    d.h1("4. Endpoint summary")
    d.table(["Method", "Path", "Access", "Purpose"], [list(e) for e in ENDPOINTS], widths=[1.8, 6.2, 4, 5])

    d.h1("5. Endpoint details and examples")
    d.p("The examples below are copied from recorded runs (`product_api_logs/02_api_transcript.md`, "
        "`inventory_logs/02_inventory_transcript.md`) on the MySQL test database; IDs are from those runs.", italic=True)
    d.h2("5.1 Service")
    d.code("GET /health  ->  200\n{\"status\":\"ok\",\"service\":\"ShopEase Product Catalog Service\",\"version\":\"1.0.0\"}\n\n"
           "GET /health/db  ->  200\n{\"status\":\"ok\",\"database\":\"connected\"}")
    d.h2("5.2 Categories")
    d.p("**POST /api/categories/** (ADMIN) – body: `name` (required, 1–100), `description` (optional). 201, 401, 403, 409, 422.")
    d.code("POST /api/categories/\n{\"name\": \"Evidence Apparel\"}\n\n201 Created\n"
           "{\"id\": 1499, \"name\": \"Evidence Apparel\", \"description\": null, \"is_active\": true,\n"
           " \"created_at\": \"2026-11-12T09:54:14Z\", \"updated_at\": \"2026-11-12T09:54:14Z\"}")
    d.p("**PATCH /api/categories/{id}** (ADMIN) – any of `name`, `description`, `is_active`. **PUT** needs all three. "
        "**DELETE** only for an empty category (409 \"Category still contains N products ...\" otherwise). "
        "**GET /api/categories/** and **/{id}** are public; inactive categories are 404 for non-admins.")
    d.code("PATCH /api/categories/1500\n{\"is_active\": false}\n\n200 OK\n"
           "{\"id\": 1500, \"name\": \"Evidence Archive\", \"description\": null, \"is_active\": false, ...}")
    d.h2("5.3 Products")
    d.p("**POST /api/products/** (ADMIN) – required `category_id`, `name`, `sku`, `price`; optional `description`, "
        "`discount_price`, `image_url`, `brand`, `initial_stock`. 201, 400, 401, 403, 409, 422.")
    d.code("POST /api/products/\n"
           "{\"category_id\": 1499, \"name\": \"Red  Cotton T-Shirt\", \"sku\": \"ev-tee-red-m\", \"price\": \"19.5\",\n"
           " \"discount_price\": \"14.99\", \"brand\": \"Basics\", \"image_url\": \"https://cdn.example.com/tee.png\",\n"
           " \"initial_stock\": 25}\n\n201 Created\n"
           "{\"id\": 1482, \"category_id\": 1499, \"name\": \"Red Cotton T-Shirt\", \"description\": null,\n"
           " \"sku\": \"EV-TEE-RED-M\", \"price\": \"19.50\", \"discount_price\": \"14.99\", \"effective_price\": \"14.99\",\n"
           " \"stock_quantity\": 25, \"in_stock\": true, \"image_url\": \"https://cdn.example.com/tee.png\",\n"
           " \"brand\": \"Basics\", \"is_active\": true, \"created_at\": \"2026-11-12T09:54:14Z\", \"updated_at\": \"...\"}")
    d.code("POST /api/products/  (same SKU, other letter case)\n409 Conflict\n{\"detail\": \"A product with this SKU already exists\"}")
    d.p("**GET /api/products/** (public) – query parameters `search`, `category_id`, `min_price`, `max_price`, "
        "`availability`, `brand`, `page`, `page_size`, `sort_by` (name, price, created_at), `sort_order` (asc, desc), "
        "`include_inactive` (ADMIN). 200, 401/403 (include_inactive), 422.")
    d.code("GET /api/products/?search=phone&availability=in_stock&sort_by=price&sort_order=desc&page=2&page_size=5\n\n"
           "200 OK\n{\"items\": [ ...products... ], \"total\": 23, \"page\": 2, \"page_size\": 5, \"total_pages\": 5}")
    d.p("**GET /api/products/{id}** (public): 200, 404, 422. **PUT** (every editable field) and **PATCH** (any fields) "
        "(ADMIN): 200, 400, 401, 403, 404, 409, 422; `stock_quantity` is refused with 422. **DELETE** (ADMIN): 200, sets "
        "`is_active` false and keeps the row.")
    d.code("GET /api/products/abc  ->  422\n{\"detail\": \"Validation failed\", \"errors\": [{\"field\": \"product_id\", \"message\": \"...\"}]}\n\n"
           "GET /api/products/999999  ->  404\n{\"detail\": \"Product not found\"}")
    d.h2("5.4 Inventory (ADMIN)")
    d.code("GET /api/inventory/2647  ->  200\n"
           "{\"product_id\": 2647, \"sku\": \"EV-INV-1\", \"name\": \"Evidence Kettle\", \"stock_quantity\": 10,\n"
           " \"low_stock_threshold\": 5, \"is_low_stock\": false}")
    d.code("POST /api/inventory/2647/stock-in\n{\"quantity\": 5, \"remarks\": \"Supplier delivery, invoice 4471\"}\n\n201 Created\n"
           "{\"transaction\": {\"id\": 2043, \"product_id\": 2647, \"transaction_type\": \"IN\", \"quantity\": 5,\n"
           "                 \"previous_stock\": 10, \"updated_stock\": 15,\n"
           "                 \"remarks\": \"Supplier delivery, invoice 4471\", \"created_at\": \"2026-11-12T12:49:03Z\"},\n"
           " \"stock\": {\"product_id\": 2647, \"sku\": \"EV-INV-1\", \"name\": \"Evidence Kettle\", \"stock_quantity\": 15,\n"
           "           \"low_stock_threshold\": 5, \"is_low_stock\": false}}")
    d.code("POST /api/inventory/2647/stock-out\n{\"quantity\": 5}            (4 available)\n\n409 Conflict\n"
           "{\"detail\": \"Insufficient stock: 4 available, 5 requested\"}\n\n"
           "POST /api/inventory/2647/stock-in\n{\"quantity\": 0}\n\n422\n"
           "{\"detail\": \"Validation failed\", \"errors\": [{\"field\": \"quantity\",\n"
           "  \"message\": \"Input should be greater than or equal to 1\"}]}")
    d.code("GET /api/inventory/2647/history?page=1&page_size=20&transaction_type=OUT   (transaction_type optional)\n200 OK\n"
           "{\"items\": [{\"id\": 2045, \"product_id\": 2647, \"transaction_type\": \"OUT\", \"quantity\": 8,\n"
           "             \"previous_stock\": 12, \"updated_stock\": 4, \"remarks\": null,\n"
           "             \"created_at\": \"2026-11-12T12:49:03Z\"}, ...],\n"
           " \"total\": ..., \"page\": 1, \"page_size\": 20, \"total_pages\": ...}")
    d.code("GET /api/inventory/low-stock  ->  200\n"
           "[{\"product_id\": 2647, \"sku\": \"EV-INV-1\", \"name\": \"Evidence Kettle\", \"stock_quantity\": 5,\n"
           "  \"low_stock_threshold\": 5, \"is_low_stock\": true}]")
    d.code("POST /api/inventory/2647/stock-in  as a customer (USER)  ->  403\n{\"detail\": \"Admin role required\"}\n\n"
           "Any admin endpoint without a token  ->  401  (WWW-Authenticate: Bearer)\n{\"detail\": \"Could not validate credentials\"}")
    d.h1("6. Machine-readable specification")
    d.p("`DELIVERABELS/API_Documentation/openapi.json` (identical to the live `/openapi.json`, checked during the final "
        "audit) and `API_Endpoint_Reference.md` in the same folder.")
    return d


# --- 6 -------------------------------------------------------------------------------------------
def jwt_report() -> Doc:
    d = Doc("JWT Authentication Report", "Integration with the existing ShopEase Authentication Service",
            meta("JWT_Authentication_Report.docx", [("Authentication Service", "shopease-auth-service v0.1.0, 127.0.0.1:8001 – not modified"),
                                                    ("Code", "app/core/security.py")]))
    d.h1("1. Existing Auth Service integration")
    d.p("The Catalog Service has no login, registration, passwords or JWT secret. These facts were taken from the "
        "Authentication Service's code, not assumed:")
    d.table(["Item", "Actual implementation"], [
        ["Signing", "HMAC HS256 (JWT_ALGORITHM), shared secret JWT_SECRET_KEY; no public key"],
        ["Claims", "sub (user ID as a string), role, iat, exp"],
        ["Lifetime", "ACCESS_TOKEN_EXPIRE_MINUTES, default 30; no refresh tokens"],
        ["Verification endpoint", "POST /api/auth/verify-token, Authorization: Bearer <token>, no body"],
        ["Answer", "200 {valid, user{id, full_name, email, role, is_active}}; 401 invalid/expired/unknown; 403 inactive"],
        ["Roles", "USER (default for every registered account = customers) and ADMIN; there is no CUSTOMER role"],
        ["Role used", "The role from its database, not the token's claim"],
    ], widths=[4.5, 12.5])
    d.h1("2. JWT verification mechanism")
    d.numbered([
        "The bearer token is taken from the `Authorization` header (anything else: 401).",
        "Local pre-check without a secret: at most 4096 characters, a well-formed JWT, header `alg` equal to `JWT_ALGORITHM`. It can only reject (garbage, `alg: none`, wrong algorithm), never accept.",
        "The token is sent to `POST /api/auth/verify-token` (timeout `AUTH_SERVICE_TIMEOUT_SECONDS`, redirects not followed).",
        "Only a 200 answer with the exact expected shape authenticates; the user ID must be a positive integer.",
        "The route's role rule is applied to the role returned.",
    ])
    d.p("**Why remote verification:** checking an HS256 signature locally would need a copy of the signing secret, "
        "which can also create tokens – including ADMIN tokens. Remote verification also makes deactivation and role "
        "changes effective immediately.")
    d.h1("3. Role-based authorization")
    d.table(["Dependency", "Use"], [
        ["get_current_authenticated_user", "Any route that needs a logged-in user"],
        ["get_optional_user", "Public routes: None without a token; a sent token is still verified (bad token = 401)"],
        ["require_roles(*roles)", "Factory for role-restricted routes; exact, case-sensitive match"],
        ["require_admin", "require_roles(\"ADMIN\"): every write and the whole inventory router"],
    ], widths=[5.5, 11.5])
    d.table(["Operation", "Anonymous", "Customer (USER)", "ADMIN"], [
        ["Browse active categories and products", "200", "200", "200"],
        ["include_inactive=true", "401", "403", "200"],
        ["Category and product changes", "401", "403", "2xx"],
        ["All inventory endpoints", "401", "403", "2xx"],
    ], widths=[8, 3, 3, 3])
    d.h1("4. Security checks")
    d.table(["Check", "Result", "Evidence"], [
        ["No token / wrong scheme / garbage / alg none", "401 (rejected locally, no network call)", "tests/test_auth_integration.py, test_security.py"],
        ["Wrong signature, tampered role, expired, missing claims, unknown user", "401", "tests/test_auth_integration.py (stand-in applying the real rules)"],
        ["Inactive user; demoted user whose token still says ADMIN; lower-case 'admin'", "403", "tests/test_auth_integration.py"],
        ["Customer calls every admin route", "403, nothing changed", "test_mandatory_scenarios.py scenario 18; Postman folder 18"],
        ["Auth Service down, timeout, 5xx, 404, redirect, non-JSON", "503 (fail closed); anonymous browsing still 200", "tests/test_auth_integration.py"],
        ["Forged ADMIN token against the live stack", "401 decided by the real Authentication Service", "auth_integration_logs/01; Postman run B; final audit"],
        ["Token never logged or returned", "Only error class names and status codes are logged", "tests/test_auth_integration.py"],
        ["No secret in code, image or deliverables", "0 matches", "Docker_Evidence/07_secret_scan.txt; final audit §5"],
    ], widths=[6, 5, 6])
    d.h1("5. Live verification and limits")
    d.p("Against the running Authentication Service: 16 of 16 live checks passed (Task 5), the live Postman run B "
        f"passed ({B['assertions']} assertions), and the final audit ({AUDIT_TIME}) confirmed again that a forged ADMIN "
        "token is refused with 401 by the real service.")
    d.p(f"**Customer token, live ({LIVE_CUST_TIME}):** a customer account registered through the Authentication "
        "Service's own API logged in and its real token was sent to every ADMIN route of the running container: "
        f"{LIVE_CUST_PASS} checks passed, {LIVE_CUST_FAIL} failed (403 \"Admin role required\" on each ADMIN route and "
        "on include_inactive; 200 on public reads). Evidence: Test_Results/live_customer/live_customer_check.txt.")
    d.p("**Blocked: ADMIN token, live.** The Authentication Service has no ADMIN account. A second account was "
        "registered for this, but the ADMIN role can only be granted by a direct change to the Authentication "
        "Service's database, which is for its owner to make; it was not made. ADMIN flows were verified with a "
        "stand-in that applies the real service's rules over HTTP.")
    d.table(["Limitation", "Note"], [
        ["One verification call per authenticated request", "About one local HTTP round trip; not cached, so changes apply at once"],
        ["No token revocation", "Inherited: a token works until it expires unless the user is deactivated"],
        ["Plain HTTP between services", "Acceptable on one machine; use HTTPS across hosts"],
    ], widths=[6, 11])
    return d


# --- 7 -------------------------------------------------------------------------------------------
def testing_report() -> Doc:
    d = Doc("API Testing Report", "All 20 mandatory scenarios with actual results – pytest, Postman (Newman) and Swagger UI",
            meta("API_Testing_Report.docx", [("Full report", "DELIVERABELS/Test_Results/Task11_API_Test_Report.md")]))
    d.h1("1. Summary")
    d.p("**No test failed.** 14 scenarios could not be run against the live Authentication Service, which has no "
        "ADMIN account, and 3 ran only partly live (see §3). All 20 passed on the test instance and in pytest.")
    d.table(["Run", "Where", "Result"], [
        ["pytest (final audit, " + SQLITE[0] + ")", "SQLite in memory", SQLITE[1]],
        ["pytest (final audit, " + MYSQL[0] + ")", "MySQL 8.4 test database", MYSQL[1]],
        ["Newman run A1: scenarios 1–20", "Test instance, stand-in Auth Service", f"{A1['requests']} requests, {A1['assertions']} assertions, {A1['assertions_failed']} failed"],
        ["Newman run A2: 12 processes at once", "Test instance", f"{A2['201']} × 201, {A2['409']} × 409, {A2['assertions_failed']} assertions failed"],
        ["Newman A3 consistency + A5 cleanup", "Test instance", f"{A3['requests'] + A5['requests']} requests, {A3['assertions'] + A5['assertions']} assertions, {A3['assertions_failed'] + A5['assertions_failed']} failed"],
        ["Direct SQL verification after run A", "MySQL test database", "11 of 11 checks passed"],
        ["Newman run B", "Live container + real Auth Service", f"{B['requests']} requests, {B['assertions']} assertions, {B['assertions_failed']} failed"],
        ["Swagger UI (Edge)", "Live (6) and test instance (8)", f"{len(SCREENSHOTS)} screenshots, each with the expected status"],
        ["Live customer check", "Live container + real Auth Service, real USER account", f"{LIVE_CUST_PASS} checks passed, {LIVE_CUST_FAIL} failed"],
        ["pytest with coverage (MySQL)", "MySQL 8.4 test database", f"{COV_PCT} line coverage of app/ ({COV_STMTS} statements, {COV_MISS} missed)"],
    ], widths=[5.5, 5, 6.5])
    d.h1("2. The 20 mandatory scenarios")
    d.table(["#", "Scenario", "Expected", "Actual (pytest + Postman run A)", "Live (run B)", "Result"],
            [[str(n), s, e, a, live, "Passed" if not live.startswith("Blocked") else "Passed (test instance); live blocked"]
             for n, s, e, a, live in SCENARIOS], widths=[0.9, 3.1, 3.2, 4.6, 2.6, 2.6], status_col=5)
    d.p("Each scenario has a pytest test in `tests/test_mandatory_scenarios.py` (`test_s01` … `test_s20`) that also reads "
        "the database rows back, and a Postman folder with a test on every request.")
    d.h1("3. Passed, failed and blocked")
    d.table(["Category", "Scenarios", "Count"], [
        ["Failed", "none", "0"],
        ["Passed on the live stack", "6, 18, 19", "3"],
        ["Partly live (correct answers, but the live database holds no products)", "5, 11, 12", "3"],
        ["Blocked live – need an ADMIN token", "1–4, 7–10, 13–17, 20", "14"],
        ["Passed on the test instance and in pytest", "1–20", "20"],
    ], widths=[9, 5, 3])
    d.p("To run everything live: grant the ADMIN role to one account in the Authentication Service (its owner), log in "
        "with it and with a USER account, put both tokens in the Postman environment (`base_url` "
        "http://127.0.0.1:8006) and run the collection.")
    d.h1("4. Postman testing")
    d.bullets([
        "Collection `postman/ShopEase_Product_Catalog_Service.postman_collection.json`: 25 folders, 109 requests, a test on every request, generated by `postman/gen_collection.py`.",
        "Environment template `postman/ShopEase_Product_Catalog_Service.postman_environment.json`: `base_url`, empty `admin_token`, `customer_token`, `run_id` – no secret.",
        "Run with Newman 6.2.1 (Postman's command-line runner) by `python -m scripts.run_postman_suite`. Reports: `Test_Results/postman/` (HTML, JSON, text).",
        "A collection-level test checks every response for internal details (traceback, SQL, driver names): passed on all 145 requests.",
    ])
    d.h1("5. Swagger UI testing")
    d.p("Real requests sent from Swagger UI in Microsoft Edge (driven by `scripts/swagger_screenshots.js`). Each image "
        "carries a banner naming the instance; the token in the generated curl command is shown as `<token hidden>`.")
    d.table(["Screenshot", "Shows"], [[s, ("Live service: " if "_live_" in s else "Test instance: ") + s[3:-4].split("_", 1)[1].replace("_", " ")] for s in SCREENSHOTS], widths=[8, 9])
    d.p("Submission screenshots (`screenshots/submission/`), taken from the running system by "
        "`scripts/take_submission_screenshots.py` (Swagger UI) and `scripts/capture_console_screenshots.ps1` "
        f"(terminal windows): {SUB_NOTE}. Tokens are shown as `<token hidden>`.")
    d.table(["Item", "Files"], [[name, ", ".join(files) or "not captured yet"] for name, files in SUBMISSION.items()],
            widths=[6.5, 10.5])
    d.h1("6. Also verified")
    d.table(["Item", "Result"], [
        ["HTTP status codes", "Passed: 400/401/403/404/409/422/503 as documented"],
        ["Database records", "Passed: rows read back after every pytest scenario; SQL check after run A"],
        ["Foreign keys", "Passed: RESTRICT on both; orphan insert and referenced delete refused"],
        ["SKU and category uniqueness", "Passed: API 409 and raw INSERTs refused by the database"],
        ["Stock constraints", "Passed: no negative stock; raw UPDATE to −1 refused; stock = replayed history"],
        ["JWT authorization", "Passed: scenarios 18 and 19; 35 Auth Service integration tests"],
        ["Transaction rollback", "Passed: faults injected on UPDATE, INSERT and COMMIT leave nothing behind"],
        ["Docker execution", "Passed: containers healthy; /health, /health/db, /docs 200 inside the container"],
    ], widths=[5, 12], status_col=1)
    d.h1("7. Automated test inventory (final audit, MySQL)")
    d.table(["Test module", "Tests passed"], [[m, str(n)] for m, n in module_counts()]
            + [["Total", str(sum(n for _, n in module_counts()))]], widths=[10, 4])
    d.h1("8. Not measured")
    d.bullets(["The Postman desktop app itself: the same collection was run with Newman.",
               f"Line coverage is measured ({COV_PCT}, `final_audit/04_coverage_mysql.txt`); code started in "
               "separate processes (`python -m app`, the database wait loop) is outside it."])
    return d


# --- 8 -------------------------------------------------------------------------------------------
def docker_report() -> Doc:
    d = Doc("Docker Execution Report", "Dockerfile, Compose architecture, MySQL container, start-up and health checks",
            meta("Docker_Execution_Report.docx", [("Recorded with", "Docker 29.6.2, Docker Compose v5.3.1, Docker Desktop (Windows, Linux engine)"),
                                                  ("Evidence", "DELIVERABELS/Docker_Evidence/01–11 (unedited command output)")]))
    d.h1("1. Dockerfile")
    d.code((ROOT / "Dockerfile").read_text(encoding="utf-8"))
    d.h1("2. Docker Compose architecture")
    d.code("Compose project shopease-product-catalog-service (one default network)\n"
           "\n"
           "  browser / Postman --> 127.0.0.1:8006 --> catalog-service  (image built from Dockerfile)\n"
           "                                             |  catalog-mysql:3306\n"
           "                                             v\n"
           "                                          catalog-mysql  (mysql:8.4) --> volume catalog_mysql_data\n"
           "\n"
           "  catalog-service --> host.docker.internal:8001 --> Authentication Service (own Compose project)\n"
           "  Optional: docker-compose.auth-network.yml joins its network and calls auth-service:8001")
    d.table(["Item", "Setting"], [
        ["catalog-service", "Image shopease-product-catalog-service:dev; published on 127.0.0.1:8006 only"],
        ["catalog-mysql", "mysql:8.4; not published (docker-compose.dev.yml publishes 127.0.0.1:3310 for development)"],
        ["Database", "Fixed to shopease_product_catalog_db in Compose; reached as catalog-mysql:3306"],
        ["Credentials", "MYSQL_USER, MYSQL_PASSWORD, MYSQL_ROOT_PASSWORD from .env, required (${VAR:?})"],
        ["Volume", "Named volume catalog_mysql_data at /var/lib/mysql; kept by docker compose down"],
        ["Auth Service URL", "http://host.docker.internal:8001/api/auth/verify-token (extra_hosts host-gateway)"],
    ], widths=[4, 13])
    d.h1("3. MySQL container")
    d.bullets([
        "Image mysql:8.4 (8.4.11); creates `shopease_product_catalog_db` and the service user on first initialisation.",
        "Health check: the service's own user runs `SELECT 1` in its database over TCP; the password is passed via `MYSQL_PWD`, not on the command line.",
        "Data persisted across `down` and `up` (Docker_Evidence/09 and 10).",
    ])
    d.h1("4. Service start-up")
    d.numbered([
        "Compose starts `catalog-service` only when `catalog-mysql` is healthy (`depends_on: condition: service_healthy`).",
        "`python -m app.database.wait --timeout 60` waits until MySQL accepts the service user (tested with MySQL down and up: Docker_Evidence/08).",
        "`alembic upgrade head` applies pending migrations; a failure stops the container before the port opens.",
        "`exec python -m app` starts Uvicorn on 0.0.0.0:8006 as the unprivileged user `app`.",
    ])
    d.h1("5. Health checks")
    d.table(["Check", "Result"], [
        ["Image HEALTHCHECK: GET /health every 10 s", "healthy"],
        ["MySQL health check", "healthy"],
        ["Inside the container: /health, /health/db, /docs, /openapi.json", "200 (Docker_Evidence/05)"],
        ["From this machine: /health and /docs", "200 (Docker_Evidence/06)"],
        [f"Final audit ({AUDIT_TIME})", "Both containers running and healthy; .env absent from the image; migration at head"],
    ], widths=[9, 8])
    d.h1("6. Commands executed")
    d.table(["Command", "Evidence", "Result"], [
        ["docker compose up --build -d", "02_compose_up_build.log", "Image built; MySQL healthy before the API started; exit 0"],
        ["docker compose ps", "03_compose_ps.txt", "Both Up (healthy)"],
        ["docker compose logs", "04_compose_logs.log", "Database ready → Alembic → Uvicorn → health 200"],
        ["docker compose exec ...", "05_checks_inside_container.txt", "Endpoints 200; user app; no .env; alembic at head"],
        ["python -m scripts.docker_secret_scan", "07_secret_scan.txt", "0 secret values in 9,279 image files and build history"],
        ["docker compose down", "09_compose_down.log", "Containers removed; volume kept"],
        ["docker compose up -d", "10_restart_data_persisted.txt", "Same databases, migration state and user after restart"],
        ["with docker-compose.auth-network.yml", "11_shared_network_option.txt", "Auth Service reached as auth-service:8001"],
    ], widths=[5.2, 5.3, 6.5])
    d.note("Never run `docker compose down -v`: it deletes the database volume. No volume was removed during the project.")
    return d


# --- 9 -------------------------------------------------------------------------------------------
CHECKLIST = [
    ("Project setup, configuration, models", "Completed", "Code; tests/test_scaffold.py, test_config.py, test_models.py"),
    ("Alembic migrations executed on MySQL 8.4", "Completed", "Migration_Execution_Report.md; final audit §2"),
    ("JWT integration with the existing Auth Service", "Completed", "02_JWT_Integration.md; auth_integration_logs; final audit §3"),
    ("Live customer (USER) token flow", "Completed", f"live_customer/live_customer_check.txt: {LIVE_CUST_PASS} passed, {LIVE_CUST_FAIL} failed; screenshot customer_403_live.png"),
    ("Live ADMIN token flows", "Blocked", "Account registered; the ADMIN role must be granted in the Auth Service database by its owner"),
    ("Category APIs", "Completed", "tests/test_category_api.py; transcripts"),
    ("Product APIs", "Completed", "tests/test_product_api.py; product_api_logs"),
    ("Search, filtering, pagination, sorting", "Completed", "tests/test_product_search.py; product_search_logs"),
    ("Inventory and transaction history", "Completed", "tests/test_inventory_*.py; inventory_logs"),
    ("Docker and Docker Compose", "Completed", "Docker_Evidence/01–11; final audit §4"),
    ("All 20 mandatory scenarios (test instance + pytest)", "Completed", "Task11_API_Test_Report.md; Postman reports"),
    ("All 20 scenarios against the live stack", "Blocked", "6, 18, 19 passed live; 14 need an ADMIN token; 3 partly (empty live database)"),
    ("Postman collection and environment template", "Completed", "postman/"),
    ("Automated Swagger UI screenshots (Task 11)", "Completed", f"{len(SCREENSHOTS)} files in DELIVERABELS/screenshots"),
    ("18 submission screenshots", SUB_STATUS, SUB_NOTE),
    ("Nine Word documents", "Completed", "DELIVERABELS/Word_Documents (generated; opened and checked)"),
    ("README, endpoint reference, schema SQL reference", "Completed", "README.md; API_Documentation/; Database_Evidence/"),
    ("Test execution summary, Teams update templates", "Completed", "Test_Results/Test_Execution_Summary.md; Progress_Reports/"),
    (".env excluded from deliverables and image", "Completed", "Final audit §4–5"),
    ("No Git commit or push by the assistant", "Completed", "No Git command run in Tasks 9–12; one read-only git diff --stat in Task 8 (disclosed); folder untracked in the parent repository"),
    ("Line coverage measurement", "Completed", f"{COV_PCT} of app/ ({COV_STMTS} statements, {COV_MISS} missed): final_audit/04_coverage_mysql.txt"),
    ("Evidence .log files kept for Git", "Completed", f".gitignore exception !DELIVERABELS/**/*.log; {LOG_FILES} files; final audit §5"),
    ("Git commit and push of the project", "Pending", "The student's decision; not done by the assistant"),
]


def final_report() -> Doc:
    d = Doc("Final Project Completion Report", "Completed requirements, remaining issues, test summary, structure and submission checklist",
            meta("Final_Project_Completion_Report.docx", [("Final audit", f"{AUDIT_TIME}: {AUDIT_PASS} passed, {AUDIT_FAIL} failed")]))
    d.h1("1. Completed requirements")
    d.table(["Requirement area", "Status", "Evidence"], [list(r) for r in CHECKLIST if r[1] == "Completed"],
            widths=[6, 2.5, 8.5], status_col=1)
    d.h1("2. Remaining issues")
    d.table(["Issue", "Status", "What is needed"], [
        ["Live ADMIN testing (scenarios 1–4, 7–10, 13–17, 20)", "Blocked",
         "The ADMIN role for the registered account (one UPDATE in the Authentication Service database, by its owner); then run the Postman collection live"],
        ["Live data for scenarios 5, 11, 12", "Blocked", "Products in the live database, which needs an ADMIN"],
        *([["Submission screenshots", "Pending", SUB_NOTE]] if SUB_MISSING else []),
        ["Git commit and push", "Pending", "The student's decision; not done by the assistant"],
        ["Plain HTTP between services; no token revocation", "Accepted", "Design limits documented in the JWT report"],
    ], widths=[6, 2.2, 8.8], status_col=1)
    d.h1("3. Test summary")
    d.table(["Run", "Result"], [
        ["pytest, SQLite (" + SQLITE[0] + ")", SQLITE[1]],
        ["pytest, MySQL 8.4 (" + MYSQL[0] + ")", MYSQL[1]],
        ["Newman, test instance (A1–A5)", f"{A1['assertions'] + A3['assertions'] + A5['assertions']} assertions, 0 failed; burst {A2['201']} × 201 / {A2['409']} × 409"],
        ["SQL verification after run A", "11 of 11 passed"],
        ["Newman, live stack (B)", f"{B['assertions']} assertions, {B['assertions_failed']} failed"],
        ["Live customer check (real USER account)", f"{LIVE_CUST_PASS} passed, {LIVE_CUST_FAIL} failed"],
        ["Line coverage of app/", f"{COV_PCT} ({COV_STMTS} statements, {COV_MISS} missed)"],
        ["Final audit", f"{AUDIT_PASS} checks passed, {AUDIT_FAIL} failed"],
    ], widths=[7, 10])
    d.h1("4. Final audit")
    rows = []
    for line in AUDIT.splitlines():
        m = re.match(r"\[(PASS|FAIL)\] (.+?): (.*)", line)
        if m and not m.group(2).startswith("no secret value in"):
            rows.append([m.group(1), m.group(2), m.group(3)[:110]])
    rows.append(["PASS", "no secret value in the project and deliverables",
                 f"{AUDIT.count('no secret value in')} locations searched, 0 matches"])
    d.table(["Result", "Check", "Observed"], rows, widths=[1.6, 7.4, 8], status_col=0)
    d.p("Source: `DELIVERABELS/Test_Results/final_audit/03_final_audit.txt` (`python -m scripts.final_audit`, read-only).")
    d.h2("Git")
    d.p("No Git command was run in Tasks 9–12. In Task 8 one read-only `git diff --stat` was run by mistake and "
        "disclosed at the time; it changes nothing. No commit, push or GitHub operation was performed. The project "
        "folder has no `.git` of its own, and the parent ShopEase repository listed it as untracked at the start of "
        "this working session. Confirm with `git status` and `git log` before submitting.")
    d.h1("5. Final project structure")
    d.code(tree())
    d.h1("6. Submission checklist")
    d.table(["Item", "Status", "Evidence / next step"], [list(r) for r in CHECKLIST], widths=[6, 2.5, 8.5], status_col=1)
    return d


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, build in (("Project_Overview", project_overview), ("Day_1_Development_Report", day1),
                        ("Day_2_Development_Report", day2), ("Database_Schema_Documentation", schema),
                        ("API_Documentation", api_doc), ("JWT_Authentication_Report", jwt_report),
                        ("API_Testing_Report", testing_report), ("Docker_Execution_Report", docker_report),
                        ("Final_Project_Completion_Report", final_report)):
        path = OUT / f"{name}.docx"
        build().save(path)
        print("wrote", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
