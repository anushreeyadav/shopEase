"""Generates the four submission Word documents in DELIVERABELS/Word_Documents/.

    pip install python-docx==1.2.0      (a documentation tool only; not a service dependency)
    python scripts/generate_word_documents.py

The content is taken from the Markdown reports in DELIVERABELS/ (01-10) and the saved
outputs in DELIVERABELS/Test_Results/. Update those first, then regenerate. Only results of
commands that were actually run are included; nothing here is marked as passed otherwise.
"""
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = Path(__file__).resolve().parent.parent / "DELIVERABELS" / "Word_Documents"
REPORT_DATE = date(2026, 11, 11)
NAVY = RGBColor(0x1F, 0x3A, 0x5F)
GREY = RGBColor(0x59, 0x59, 0x59)
HEADER_FILL = "1F3A5F"
BAND_FILL = "EEF2F7"

# --- shared facts (each one is recorded in DELIVERABELS/) -------------------------------------

PROJECT = "ShopEase User Management Microservice"
STATUS = ("Core service complete and verified. Screenshots captured (20 of 20, plus 5 extra). "
          "Not done: admin endpoints (list, read, reactivate).")

OBJECTIVE = (
    "Build an independent microservice that manages customer profiles and saved delivery addresses "
    "for the ShopEase e-commerce platform. It must use identities issued and verified by the existing "
    "Authentication Service, without ever holding that service's JWT secret, and must guarantee that "
    "no customer can read or change another customer's data. It has its own MySQL database, migrated "
    "with Alembic, runs in Docker Compose, and comes with automated tests and documentation."
)

TECH_STACK = [
    ("Language", "Python 3.11"),
    ("Web framework", "FastAPI 0.162, Uvicorn 0.54"),
    ("Database", "MySQL 8.4 (Docker image mysql:8.4), database shopease_user_db, utf8mb4"),
    ("ORM and migrations", "SQLAlchemy 2.1, PyMySQL 1.2, Alembic 1.20"),
    ("Validation and settings", "Pydantic 2.14, pydantic-settings 2.16"),
    ("Calls to the Authentication Service", "HTTPX 0.28"),
    ("Containers", "Docker Engine 29.6.2, Docker Compose v5.3.1"),
    ("Tests", "pytest 9.2, FastAPI TestClient, Newman 6.2.1 (Postman collection runner)"),
]

ENDPOINTS = [
    ("POST", "/api/users/profile", "Create the caller's profile", "201; 409 if it exists"),
    ("GET", "/api/users/profile", "Read the caller's profile", "200; 404 if none"),
    ("PUT", "/api/users/profile", "Replace the profile (omitted optional fields are cleared)", "200"),
    ("PATCH", "/api/users/profile", "Update some fields", "200"),
    ("DELETE", "/api/users/profile", "Deactivate the profile (same as PATCH /account/deactivate)", "200"),
    ("GET", "/api/users/account", "Authentication account and profile together", "200"),
    ("PATCH", "/api/users/account/contact", "Change the phone number (email stays with the Authentication Service)", "200"),
    ("PATCH", "/api/users/account/deactivate", "Deactivate the local profile only; records kept", "200"),
    ("POST", "/api/users/addresses", "Add an address; the first one becomes the default", "201"),
    ("GET", "/api/users/addresses", "List own addresses, default first", "200"),
    ("GET", "/api/users/addresses/default", "The default delivery address", "200; 404 if none"),
    ("GET", "/api/users/addresses/{address_id}", "One own address", "200; 404 if missing or another user's"),
    ("PUT", "/api/users/addresses/{address_id}", "Replace an address", "200"),
    ("DELETE", "/api/users/addresses/{address_id}", "Delete; if it was the default, the oldest remaining one becomes the default", "200"),
    ("PATCH", "/api/users/addresses/{address_id}/default", "Make it the only default", "200"),
]

ERRORS = [
    ("401", "Could not validate credentials", "Missing, malformed, tampered or expired token (from the Authentication Service)"),
    ("403", "Inactive user", "Account deactivated in the Authentication Service"),
    ("403", "User profile is deactivated", "Any profile, address or account endpoint after the local profile was deactivated"),
    ("404", "User profile not found", "No profile created yet"),
    ("404", "Address not found", "Address missing, deleted, or belonging to another user (identical response)"),
    ("404", "Default address not found", "The caller has no addresses"),
    ("409", "User profile already exists", "Second POST /api/users/profile"),
    ("422", "Validation failed", "Invalid body or path value; names the field, never repeats the value. "
                                 "Also any client-supplied auth_user_id, user_id or id (extra fields are forbidden)"),
    ("503", "Authentication service unavailable", "Authentication Service down, slow, failing, or sending a malformed response"),
    ("503", "Service temporarily unavailable", "Database unavailable"),
    ("500", "Internal server error", "Unexpected error; no internal details returned"),
]

PROFILE_COLUMNS = [
    ("id", "int", "NO", "Primary key, auto increment"),
    ("auth_user_id", "int", "NO", "Authentication Service user ID. UNIQUE (uq_user_profiles_auth_user_id). No cross-database FK"),
    ("full_name", "varchar(255)", "NO", ""),
    ("phone_number", "varchar(20)", "YES", "Normalized (digits, optional leading +)"),
    ("date_of_birth", "date", "YES", "Not in the future"),
    ("gender", "varchar(20)", "YES", "MALE, FEMALE, OTHER, PREFER_NOT_TO_SAY. CHECK ck_user_profiles_gender"),
    ("profile_image", "varchar(500)", "YES", "http or https URL"),
    ("is_active", "tinyint(1)", "NO", "Local profile status, default 1"),
    ("created_at", "datetime", "NO", "UTC, default now()"),
    ("updated_at", "datetime", "NO", "UTC, changes on every update"),
]

ADDRESS_COLUMNS = [
    ("id", "int", "NO", "Primary key, auto increment"),
    ("user_id", "int", "NO", "FK to user_profiles.id, ON DELETE CASCADE, indexed"),
    ("address_type", "varchar(20)", "NO", "HOME, OFFICE, OTHER; default HOME. CHECK ck_user_addresses_address_type"),
    ("full_name", "varchar(255)", "NO", "Recipient name"),
    ("phone_number", "varchar(20)", "NO", "Recipient phone, normalized"),
    ("address_line_1", "varchar(255)", "NO", ""),
    ("address_line_2", "varchar(255)", "YES", "Optional"),
    ("city", "varchar(100)", "NO", ""),
    ("state", "varchar(100)", "NO", ""),
    ("country", "varchar(100)", "NO", ""),
    ("postal_code", "varchar(20)", "NO", "3-20 letters, digits, spaces or hyphens"),
    ("is_default", "tinyint(1)", "NO", "At most one true per profile"),
    ("default_marker", "int", "YES", "STORED GENERATED: 1 when is_default, else NULL. UNIQUE (user_id, default_marker)"),
    ("created_at", "datetime", "NO", "UTC, default now()"),
]

PYTEST_FILES = [
    ("test_address_api.py", "125", "All address endpoints: validation, ownership, default rules, locking, rollback"),
    ("test_account_api.py", "67", "Account endpoints, contact update, deactivation policy, default address"),
    ("test_user_profile_api.py", "87", "All profile endpoints, validation, identity spoofing, scoping"),
    ("test_auth_integration.py", "57", "Verify-token integration: 401/403/503 mapping, malformed responses, no token leaks"),
    ("test_database_layer.py", "17", "Models, constraints, phone normalization, session rollback"),
    ("test_scaffold.py", "15", "Startup, health, settings, API_PREFIX validation, no JWT secret"),
    ("test_security_audit.py", "150", "Security audit test cases 1-20 and the security requirements, through the real verification path"),
]

TEST_CASES = [
    ("1", "Access profile without JWT", "401, Authentication Service not called"),
    ("2", "Access profile with invalid JWT (9 kinds)", "401 for each"),
    ("3", "Access profile with expired JWT", "401"),
    ("4", "Access profile with valid JWT", "200, own profile"),
    ("5", "Create duplicate profile", "409, still one row"),
    ("6", "Retrieve own profile", "200, own data only"),
    ("7", "Update own profile", "200, saved"),
    ("8", "Access another user's profile (23 attempts)", "Never possible: ignored IDs, 422 on identity fields, no such routes"),
    ("9", "Create own address", "201, owned by own profile"),
    ("10", "Retrieve own addresses", "Own addresses only"),
    ("11", "Update own address", "200, saved"),
    ("12", "Delete own address", "200, row gone"),
    ("13", "Read another user's address by changing address_id", "404, identical to a missing ID"),
    ("14", "Modify another user's address", "404, nothing changed"),
    ("15", "Set an address as default", "200, the only default"),
    ("16", "Try to create two default addresses", "Never two; a direct database insert is refused by the unique key"),
    ("17", "Only one default exists", "Exactly 1 after every operation"),
    ("18", "Deactivate a profile", "200, record kept"),
    ("19", "Inactive profile cannot manage addresses", "403 on all 7 address endpoints"),
    ("20", "User Service does not change the Authentication Service account", "No change; verify-token calls only"),
]

LIVE_AUDIT = [
    ("Health", "3", "/health, /health/db (database connected), /"),
    ("Real users", "4", "Register and log in users A and B on the Authentication Service"),
    ("JWT verification", "6", "No token, malformed, altered signature, Basic scheme: 401. Real token: 200 with the token's identity"),
    ("Profile", "10", "404 before creation; client auth_user_id refused (422); create 201; duplicate 409; GET; PUT; PATCH; invalid phone 422"),
    ("Account", "4", "Contact update normalizes the phone; email refused (422); profile ACTIVE"),
    ("Addresses", "22", "First address default; default moves; identity and type validation; one default listed first; "
                        "GET/PUT; set default; delete default promotes the oldest; deleted 404; ID 0 gives 422"),
    ("Ownership", "11", "B's GET, PUT, PATCH default and DELETE on A's addresses: 404. Lists separate. A's data unchanged"),
    ("Deactivation", "13", "Deactivate 200 (authentication account unchanged); then 403 on 7 calls; token still valid at the "
                           "Authentication Service; login still works; B unaffected"),
]

LIVE_JWT = [
    ("Log in on the Authentication Service", "200 + token", "200 (token redacted)", "Pass"),
    ("Protected endpoint with that token", "200", "200, auth_user_id equals the logged-in user", "Pass"),
    ("No Authorization header", "401", "401", "Pass"),
    ("Token with its signature changed", "401", "401", "Pass"),
    ("Malformed token, Basic scheme", "401", "401", "Pass"),
    ("Profile deactivated in the User Service", "403; token still valid", "403 on 7 calls; verify-token 200; login 200", "Pass"),
    ("Authentication Service stopped", "503", "503; 200 again after restart", "Pass"),
    ("Token in either service's logs", "Not present", "Not found (whole token or signature)", "Pass"),
    ("Real expired token (30-minute expiry)", "401", "Not run live; covered by automated test case 3", "Not run live"),
    ("Account inactive in the Authentication Service", "403", "Not run live; covered by automated tests", "Not run live"),
    ("USER / ADMIN token on admin endpoints", "403 / 200", "Not applicable: admin endpoints not implemented", "N/A"),
]

FINDINGS = [
    ("1", "Low", "Unexpected exceptions returned plain-text 500", "Fixed: JSON 500 without details"),
    ("2", "Low", "No limit on addresses per customer", "Open"),
    ("3", "Low", "No rate limiting", "Open (recommend at the API gateway)"),
    ("4", "Info", "Swagger UI and OpenAPI enabled by default", "Set DOCS_ENABLED=false in production"),
    ("5", "Info", "Sequential database IDs in responses", "Accepted: foreign IDs give the same 404 as missing ones"),
]

DOCKER_CONFIG = [
    ("Dockerfile", "python:3.11-slim-bookworm; WORKDIR /app; requirements installed first; copies only app/, alembic/, "
                   "alembic.ini; runs as unprivileged user app (uid 999); EXPOSE 8002; health check on /health"),
    ("Startup command", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8002: the API "
                        "starts only if the migrations succeed"),
    ("user-mysql", "mysql:8.4; database shopease_user_db; credentials from .env (required, no defaults); named "
                   "volume user_mysql_data; health check mysqladmin ping; no published port"),
    ("user-service", "Built from the Dockerfile; MYSQL_HOST=user-mysql, MYSQL_PORT=3306; waits for user-mysql to be "
                     "healthy; published on 127.0.0.1:8002 only"),
    ("Authentication Service URL", "http://host.docker.internal:8001/api/auth/verify-token (separate Compose "
                                   "project, so its container name does not resolve; override with "
                                   "DOCKER_AUTH_SERVICE_VERIFY_URL)"),
    ("docker-compose.dev.yml", "Optional override that publishes MySQL on 127.0.0.1:3309 for Alembic and MySQL-mode "
                               "tests on the host"),
]

DOCKER_RESULTS = [
    ("docker compose config", "Exit 0; API_PREFIX /api, MYSQL_HOST user-mysql, host.docker.internal verify URL, only port 8002 published"),
    ("docker compose up --build -d", "Image built; user-mysql healthy before user-service started"),
    ("docker compose ps", "user-mysql Up (healthy), not published; user-service Up (healthy), 127.0.0.1:8002"),
    ("docker compose logs -f user-service", "Alembic ran, then Uvicorn started, then GET /health 200"),
    ("GET /health and /health/db", "200 ok; database connected"),
    ("Fresh empty volume", "Both migrations ran before the server started; healthy after 27 s"),
    ("Persistence", "Data unchanged after docker compose down and up"),
    ("alembic current / check (in the container)", "4f1a9d27c5e3 (head); no new upgrade operations detected"),
    (".env in the image", "Not present (find / -name '.env*' found nothing)"),
]

LIMITATIONS = [
    "Admin endpoints (list profiles, read any profile, reactivate) are not implemented. A deactivated profile "
    "therefore cannot be reactivated through the API; its records are kept.",
    "Every protected request calls the Authentication Service (no caching). If it is down, protected endpoints "
    "return 503.",
    "No limit on addresses per customer and no rate limiting (audit findings 2 and 3, open).",
    "A real expired token and a token of an account deactivated in the Authentication Service were tested only "
    "with the automated stand-in, not live.",
    "The Swagger UI walkthrough was script-driven, not clicked by hand. The Postman collection was run with Newman, not in the Postman app.",
    "The service is not added to the platform-level Docker Compose or API gateway (by instruction).",
]

PENDING = [
    ("Admin endpoints (list, read, reactivate)", "Designed in 04; not implemented"),
    ("Address limit and rate limiting", "Audit findings 2 and 3"),
    ("Post the Teams updates", "Text ready in 10_Teams_Progress_Updates.md"),
    ("Commit and push", "To be done manually by the author; nothing was committed or pushed"),
]


# --- document helpers -------------------------------------------------------------------------

def shade(cell, fill):
    props = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    props.append(shd)


def add_field(run, instruction):
    for kind, text in (("begin", None), (None, instruction), ("separate", None), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        run._r.append(el)


def new_document(title):
    doc = Document()
    section = doc.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    for side in ("left_margin", "right_margin"):
        setattr(section, side, Cm(2.2))
    section.top_margin, section.bottom_margin = Cm(2.0), Cm(2.0)

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    normal.paragraph_format.space_after = Pt(6)
    for level, size in ((1, 15), (2, 12.5), (3, 11)):
        style = doc.styles[f"Heading {level}"]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.color.rgb = NAVY
        style.font.bold = True
        style.paragraph_format.space_before = Pt(14 if level == 1 else 10)
        style.paragraph_format.space_after = Pt(4)

    header = section.header.paragraphs[0]
    header.text = f"{PROJECT}  |  {title}"
    header.runs[0].font.size, header.runs[0].font.color.rgb = Pt(8.5), GREY
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run("Page ")
    run.font.size = Pt(8.5)
    add_field(footer.add_run(), "PAGE")
    doc.core_properties.title = f"{PROJECT}: {title}"
    doc.core_properties.author = "Anushree Yadav"
    return doc


def cover(doc, title, subtitle, rows):
    for _ in range(5):
        doc.add_paragraph()
    p = doc.add_paragraph()
    run = p.add_run("ShopEase")
    run.font.size, run.font.color.rgb, run.bold = Pt(13), GREY, True
    p = doc.add_paragraph()
    run = p.add_run(title)
    run.font.size, run.font.color.rgb, run.bold = Pt(26), NAVY, True
    p = doc.add_paragraph()
    run = p.add_run(subtitle)
    run.font.size, run.font.color.rgb = Pt(13), GREY
    doc.add_paragraph()
    table(doc, None, rows, widths=(4.5, 12.0), header=False)
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def table(doc, headers, rows, widths=None, header=True):
    columns = len(headers) if headers else len(rows[0])
    t = doc.add_table(rows=0, cols=columns)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    if header and headers:
        cells = t.add_row().cells
        for cell, text in zip(cells, headers):
            cell.text = ""
            run = cell.paragraphs[0].add_run(text)
            run.bold, run.font.size, run.font.color.rgb = True, Pt(9.5), RGBColor(0xFF, 0xFF, 0xFF)
            shade(cell, HEADER_FILL)
    for i, row in enumerate(rows):
        cells = t.add_row().cells
        for j, (cell, text) in enumerate(zip(cells, row)):
            cell.text = ""
            run = cell.paragraphs[0].add_run(str(text))
            run.font.size = Pt(9.5)
            if not header and j == 0:
                run.bold = True
                shade(cell, BAND_FILL)
            elif header and i % 2 == 1:
                shade(cell, BAND_FILL)
    if widths:
        for row in t.rows:
            for cell, width in zip(row.cells, widths):
                cell.width = Cm(width)
    doc.add_paragraph()
    return t


def bullets(doc, items):
    for item in items:
        doc.add_paragraph(item, style="List Bullet")


def para(doc, text, bold_prefix=None):
    p = doc.add_paragraph()
    if bold_prefix:
        p.add_run(bold_prefix).bold = True
    p.add_run(text)
    return p


def code(doc, text):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name, run.font.size = "Consolas", Pt(8.5)
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
    p.paragraph_format.space_after = Pt(8)


def cover_rows(document_name):
    return [
        ("Project", PROJECT),
        ("Service", "shopease-user-service (FastAPI, port 8002)"),
        ("Document", document_name),
        ("Period", "10-11 November 2026 (two-day task)"),
        ("Report date", REPORT_DATE.strftime("%d %B %Y")),
        ("Status", STATUS),
    ]


ARCHITECTURE = """\
Client (Swagger UI, Postman, another service)
  | 1. POST /api/auth/login ---------------> Authentication Service :8001 (separate project)
  | <- access_token (JWT)                    owns email, password hash, role, is_active
  |                                                    ^
  | 2. GET /api/users/...  Bearer <token>              | 3. POST /api/auth/verify-token
  v                                                    |    <- 200 {valid, user{id,...}} / 401 / 403
User Service :8002  ---------------------------------- +
  routers -> services -> SQLAlchemy models
  v
MySQL 8.4 shopease_user_db (container user-mysql, volume user_mysql_data)
  user_profiles (auth_user_id UNIQUE)   user_addresses (FK user_id, one default per profile)"""

FOLDERS = """\
app/
  main.py                 FastAPI app, routers, /, /health, /health/db
  exception_handlers.py   validation, database (503) and unexpected (500) errors
  core/                   config.py, security.py (token verification), phone_utils.py
  database/connection.py  engine, session, Base
  models/                 user_model.py, address_model.py
  schemas/                user_schema.py, address_schema.py, account_schema.py
  services/               user_service.py, address_service.py, account_service.py
  routers/                user_routes.py, address_routes.py, account_routes.py
alembic/                  env.py, versions/ (8c2e3b6d4acf, 4f1a9d27c5e3)
tests/                    518 pytest tests, fake_auth_service.py
scripts/                  live_api_audit.py, generate_word_documents.py
postman/                  Postman collection
DELIVERABELS/             reports 01-10, Test_Results/, screenshots/, Word_Documents/
Dockerfile, docker-compose.yml, docker-compose.dev.yml, requirements.txt, .env.example"""


def auth_section(doc, title="Authentication integration", level=1):
    doc.add_heading(title, level)
    para(doc, "The User Service has no login, registration, password or JWT code, and does not hold the "
              "Authentication Service's JWT secret. For every protected request, the dependency "
              "get_current_authenticated_user() in app/core/security.py sends the caller's Authorization: Bearer "
              "header to POST /api/auth/verify-token on the Authentication Service and takes the caller's identity "
              "only from that response.")
    table(doc, ["Authentication Service answer", "User Service response"], [
        ("200 {valid: true, user{id, full_name, email, role, is_active}}", "Continue as user.id (auth_user_id)"),
        ("401 (missing, invalid, tampered or expired token)", "401 Could not validate credentials"),
        ("403 (account inactive)", "403 Inactive user"),
        ("Timeout, connection error, 5xx, redirect, malformed body", "503 Authentication service unavailable (fail closed)"),
    ], widths=(8.3, 8.3))
    bullets(doc, [
        "Verify URL: http://127.0.0.1:8001/api/auth/verify-token when run on the host; "
        "http://host.docker.internal:8001/api/auth/verify-token from the Docker container.",
        "The token is sent only to the configured verify URL, never logged and never returned; redirects are "
        "not followed.",
        "Client-supplied identity (auth_user_id, user_id, id in the body, query or headers) is ignored or "
        "refused with 422.",
        "Profile status is local: deactivating a profile never changes the Authentication Service account.",
    ])


# --- the four documents -----------------------------------------------------------------------

def project_overview():
    doc = new_document("Project Overview")
    cover(doc, "User Service: Project Overview", "Objective, scope, architecture and technology",
          cover_rows("Project Overview"))

    doc.add_heading("1. Objective", 1)
    para(doc, OBJECTIVE)

    doc.add_heading("2. Scope", 1)
    doc.add_heading("What the service does", 2)
    bullets(doc, [
        "Stores the customer profile: full name, phone number, date of birth, gender, profile image URL.",
        "Stores saved addresses (Home, Office, Other) with exactly one default address once any exist.",
        "Provides an account overview, a contact (phone) update, and deactivation of the local profile.",
    ])
    doc.add_heading("What it does not do", 2)
    bullets(doc, [
        "Register users, log them in, or store passwords: the Authentication Service does this.",
        "Create or decode JWTs, or hold the JWT secret.",
        "Read the Authentication Service's database.",
    ])

    doc.add_heading("3. Architecture", 1)
    para(doc, "The service has its own database and verifies every token with the Authentication Service:")
    code(doc, ARCHITECTURE)
    table(doc, ["Layer", "Responsibility"], [
        ("routers/", "HTTP only: path and body validation, status codes"),
        ("services/", "Business rules: ownership, default address, deactivation, transactions"),
        ("models/", "SQLAlchemy table definitions"),
        ("schemas/", "Pydantic request and response models (extra fields forbidden)"),
        ("core/security.py", "Token verification through the Authentication Service"),
    ], widths=(4.0, 12.6))

    doc.add_heading("4. Technology stack", 1)
    table(doc, ["Area", "Choice"], TECH_STACK, widths=(5.5, 11.1))

    doc.add_heading("5. Folder structure", 1)
    code(doc, FOLDERS)

    doc.add_heading("6. Configuration and ports", 1)
    para(doc, "All settings come from environment variables or a local .env file (Pydantic Settings). .env is "
              "excluded from Git and from the Docker image; .env.example contains placeholders only. The only "
              "secrets are the two MySQL passwords, which have no defaults and are masked in logs.")
    table(doc, ["Component", "Port"], [
        ("Authentication Service API", "8001"),
        ("User Service API", "8002 (published on 127.0.0.1 only)"),
        ("User MySQL", "Not published; 127.0.0.1:3309 only with docker-compose.dev.yml"),
    ], widths=(6.0, 10.6))

    doc.add_heading("7. API summary", 1)
    para(doc, "15 endpoints, all implemented and tested. Every one acts only on the caller's own data.")
    table(doc, ["Method", "Path", "Purpose"], [e[:3] for e in ENDPOINTS], widths=(1.8, 6.6, 8.2))

    auth_section(doc, "8. Authentication integration")

    doc.add_heading("9. Status and pending items", 1)
    para(doc, STATUS)
    table(doc, ["Pending item", "Detail"], PENDING, widths=(6.0, 10.6))
    return doc


def database_and_api():
    doc = new_document("Database and API Documentation")
    cover(doc, "User Service: Database and API Documentation", "Schema, migrations, endpoints and errors",
          cover_rows("Database and API Documentation"))

    doc.add_heading("1. Database", 1)
    para(doc, "Database shopease_user_db on MySQL 8.4 (utf8mb4 / utf8mb4_0900_ai_ci). It belongs to the User "
              "Service only. Tables are created exclusively by Alembic migrations; alembic/env.py refuses to run "
              "against any other database.")
    doc.add_heading("Relationship", 2)
    code(doc, "user_profiles (1) ----< (0..n) user_addresses\n"
              "  id  <------------------------  user_id   FK, ON DELETE CASCADE\n"
              "  auth_user_id UNIQUE  = Authentication Service user ID (no cross-database FK)")
    doc.add_heading("Table user_profiles", 2)
    table(doc, ["Column", "Type", "Null", "Rules"], PROFILE_COLUMNS, widths=(3.2, 2.8, 1.3, 9.3))
    para(doc, "The table has no email, password, password hash, token or login column; a unit test fails if one "
              "is added.")
    doc.add_heading("Table user_addresses", 2)
    table(doc, ["Column", "Type", "Null", "Rules"], ADDRESS_COLUMNS, widths=(3.2, 2.8, 1.3, 9.3))
    doc.add_heading("One default address per profile", 2)
    bullets(doc, [
        "Database: a stored generated column default_marker (1 when is_default, otherwise NULL) with the unique "
        "key uq_user_addresses_one_default_per_user (user_id, default_marker). A second default is refused even "
        "by a direct insert.",
        "Service: every address write runs in one transaction and first locks the owning profile row "
        "(SELECT ... FOR UPDATE); the old default is cleared before the new one is set; any failure rolls back.",
        "Live check on MySQL: 300 concurrent default changes from 20 threads all succeeded and left exactly 1 "
        "default. Without the lock, 219 of 300 failed (unique-key errors and deadlocks).",
        "Deleting the default promotes the oldest remaining address in the same transaction.",
    ])
    doc.add_heading("Migrations (Alembic)", 2)
    table(doc, ["Revision", "Description"], [
        ("8c2e3b6d4acf", "Create user_profiles and user_addresses, the unique auth_user_id, the foreign key with "
                         "ON DELETE CASCADE, CHECK constraints and indexes"),
        ("4f1a9d27c5e3 (head)", "Address types HOME, OFFICE, OTHER; existing WORK rows converted to OFFICE"),
    ], widths=(4.0, 12.6))
    para(doc, "Verified: upgrade and downgrade on MySQL; automatic upgrade on a new empty Docker volume before the "
              "API started; alembic current in the container shows 4f1a9d27c5e3 (head); alembic check reports no "
              "differences between the models and the database.")
    code(doc, "alembic upgrade head      alembic downgrade -1      alembic current\n"
              "alembic history           alembic check")

    doc.add_heading("2. API", 1)
    para(doc, "Base URL http://127.0.0.1:8002. Interactive documentation: /docs (Swagger UI) and /redoc. Every "
              "/api/users endpoint requires Authorization: Bearer <access token from the Authentication Service>. "
              "The service endpoints /, /health and /health/db need no token.")
    doc.add_heading("Endpoints", 2)
    table(doc, ["Method", "Path", "Purpose", "Success"], ENDPOINTS, widths=(1.6, 5.4, 6.4, 3.2))
    doc.add_heading("Errors", 2)
    para(doc, "Every error is a JSON object with detail. Validation errors also list the failing fields.")
    table(doc, ["Status", "detail", "When"], ERRORS, widths=(1.5, 5.0, 10.1))
    doc.add_heading("Validation rules", 2)
    bullets(doc, [
        "Profile: full_name required (1-255 characters); phone 7-15 digits, optional leading +, normalized; "
        "date_of_birth not in the future; gender MALE, FEMALE, OTHER or PREFER_NOT_TO_SAY; profile_image an "
        "http(s) URL.",
        "Address: address_type HOME, OFFICE or OTHER (default HOME); full_name, phone_number, address_line_1, "
        "city, state, country and postal_code required; address_line_2 optional; is_default only on create "
        "(use PATCH .../default afterwards).",
        "address_id must be a whole number from 1 to 2147483647.",
        "Unknown fields are rejected (422), so auth_user_id, user_id and id can never be sent.",
    ])
    doc.add_heading("Example: add an address", 2)
    code(doc, 'POST /api/users/addresses\nAuthorization: Bearer eyJ...\nContent-Type: application/json\n\n'
              '{"address_type": "HOME", "full_name": "Asha Rao", "phone_number": "+91 98765-43210",\n'
              ' "address_line_1": "12 MG Road", "address_line_2": "Flat 4B", "city": "Bengaluru",\n'
              ' "state": "Karnataka", "country": "India", "postal_code": "560001", "is_default": true}\n\n'
              '201 Created -> {"id": ..., "user_id": <caller\'s profile id>, "address_type": "HOME",\n'
              '                "phone_number": "+919876543210", ..., "is_default": true, "created_at": "..."}')
    doc.add_heading("Account status vs profile status", 2)
    table(doc, ["", "Authentication account status", "User Service profile status"], [
        ("Owned by", "Authentication Service", "User Service (user_profiles.is_active)"),
        ("Effect", "Inactive: every token is refused (403 Inactive user)", "Deactivated: 403 User profile is "
                                                                           "deactivated on profile, address and account endpoints"),
        ("Changed by the User Service", "Never", "PATCH /api/users/account/deactivate or DELETE /api/users/profile"),
        ("Records", "-", "Profile and addresses kept"),
    ], widths=(3.6, 6.5, 6.5))
    doc.add_heading("Planned, not implemented", 2)
    para(doc, "Admin endpoints GET /api/users, GET /api/users/{auth_user_id} and POST "
              "/api/users/{auth_user_id}/reactivate (ADMIN role) are designed but not implemented. The "
              "require_admin dependency exists and is tested.")
    auth_section(doc, "3. Authentication integration")
    return doc


def testing_report():
    doc = new_document("API Testing Report")
    cover(doc, "User Service: API Testing Report", "Automated tests, security audit and live tests",
          cover_rows("API Testing Report"))

    doc.add_heading("1. Summary", 1)
    table(doc, ["Suite", "Environment", "Result"], [
        ("pytest, full suite", "SQLite in memory", "518 passed, 0 failed"),
        ("pytest, full suite", "MySQL 8.4 shopease_user_db", "518 passed, 0 failed"),
        ("Security audit (part of the suite)", "SQLite and MySQL", "150 passed, 0 failed"),
        ("Live API audit (scripts/live_api_audit.py)", "Docker containers, real tokens", "73 of 73 checks passed"),
        ("Postman collection (Newman 6.2.1)", "Docker containers, real tokens", "28 requests, 38 of 38 assertions passed"),
        ("Swagger UI walkthrough (script-driven)", "15 steps", "20 screenshots; not clicked by hand"),
    ], widths=(6.0, 5.3, 5.3))
    para(doc, "Only tests that were actually run are reported as passed. pytest reports one warning, a Starlette "
              "deprecation in FastAPI's TestClient, which affects the tests only.")

    doc.add_heading("2. Test environment", 1)
    bullets(doc, [
        "Windows 11 Pro, Python 3.11, pytest 9.2, FastAPI TestClient.",
        "Databases: SQLite in memory, and MySQL 8.4 shopease_user_db (Alembic head 4f1a9d27c5e3). Each test runs "
        "in a transaction that is rolled back.",
        "pytest replaces the Authentication Service with a stand-in that signs and checks real HS256 tokens and "
        "returns the real verify-token responses. The security audit tests use the full verification path.",
        "Live tests: User Service in Docker on 127.0.0.1:8002; Authentication Service started unchanged from "
        "its own folder on 127.0.0.1:8001; new test users registered through its API.",
    ])

    doc.add_heading("3. Automated tests by file", 1)
    table(doc, ["File", "Tests", "Covers"], PYTEST_FILES, widths=(4.6, 1.4, 10.6))

    doc.add_heading("4. Security audit: test cases 1-20", 1)
    para(doc, "Focus: one customer must never read or change another customer's profile or addresses. Every "
              "test case passed on SQLite and on MySQL.")
    table(doc, ["#", "Test case", "Expected", "Result"], [(*tc, "Pass") for tc in TEST_CASES],
          widths=(0.8, 7.0, 7.0, 1.8))
    doc.add_heading("Security requirements", 2)
    table(doc, ["Requirement", "Result"], [
        ("No client-supplied user ID can override the JWT identity", "Pass"),
        ("All queries scoped to the authenticated owner", "Pass"),
        ("Missing or invalid authentication returns 401 (15 endpoints x 3 cases)", "Pass"),
        ("Forbidden operations return 403 (inactive account, deactivated profile)", "Pass"),
        ("Foreign resources return 404, byte-identical to missing ones", "Pass"),
        ("No passwords or authentication secrets in responses or schemas", "Pass"),
        ("No token leakage in logs (5,453 log lines scanned)", "Pass"),
        ("No internal error details in responses", "Pass"),
    ], widths=(13.6, 3.0))
    doc.add_heading("Findings", 2)
    table(doc, ["#", "Severity", "Finding", "Status"], FINDINGS, widths=(0.8, 1.8, 7.0, 7.0))
    para(doc, "Fault injection confirmed the tests detect real faults: removing the owner filter from address "
              "lookups, returning the wrong profile, logging the token, or passing Authentication Service error "
              "bodies through each made audit tests fail.")

    doc.add_heading("5. Live API tests", 1)
    doc.add_heading("Scripted audit against Docker (73 checks)", 2)
    para(doc, "Two new users, A and B, were registered and logged in on the running Authentication Service; every "
              "User Service call used their real tokens. A check passes only if both the status and the stated "
              "condition match.")
    table(doc, ["Area", "Checks", "What was shown"], LIVE_AUDIT, widths=(3.0, 1.5, 12.1))
    para(doc, "Afterwards the database showed A's profile kept with is_active = 0, A's addresses kept with one "
              "default, and no profile with more than one default. Neither token appeared in either service's logs.")
    doc.add_heading("Postman collection with Newman", 2)
    para(doc, "postman/ShopEase_User_Service.postman_collection.json: health, register/login/verify on the "
              "Authentication Service, the no-token 401, all profile, account and address endpoints, default "
              "promotion, deactivation, and login still working afterwards. Newman 6.2.1: 28 requests, 38 "
              "assertions, 0 failed.")
    doc.add_heading("JWT scenarios against the real Authentication Service", 2)
    table(doc, ["Scenario", "Expected", "Actual", "Result"], LIVE_JWT, widths=(5.0, 2.6, 6.4, 2.6))

    doc.add_heading("6. Not executed", 1)
    bullets(doc, [
        "A real expired token after the 30-minute expiry (covered by automated test case 3).",
        "A token of an account deactivated in the Authentication Service (covered by automated tests).",
        "Admin scenarios: admin endpoints are not implemented.",
        "A Swagger UI walkthrough clicked by hand (it was run by a script in Edge; screenshots 05-18).",
    ])

    doc.add_heading("7. Evidence files", 1)
    para(doc, "All in DELIVERABELS/Test_Results/, sanitized (tokens shown at most as their first 10 characters, "
              "no passwords):")
    table(doc, ["File", "Contents"], [
        ("final_pytest_sqlite.txt, final_pytest_mysql.txt", "Final pytest -v runs: 518 passed each"),
        ("security_audit_pytest_*.txt, security_audit_junit_*.xml", "Security audit runs: 150 passed each"),
        ("final_live_api_audit.txt", "Live audit output: 73/73"),
        ("postman_newman_run.txt", "Newman output: 38/38 assertions"),
        ("postman_newman_run_with_environment.txt", "Newman with the environment template: 38/38 assertions"),
        ("final_validation_checks.txt", "Token log search, database rows, Alembic, Compose validation, Git"),
        ("docker_*.txt", "Docker execution and token verification evidence"),
    ], widths=(7.0, 9.6))
    return doc


def final_report():
    doc = new_document("Final Completion Report")
    cover(doc, "User Service: Final Completion Report", "What was delivered, how it was verified, what remains",
          cover_rows("Final Completion Report"))

    doc.add_heading("1. Summary", 1)
    para(doc, "The User Service is an independent FastAPI microservice that stores customer profiles and saved "
              "addresses in its own MySQL database. Every request is authenticated by sending the caller's token "
              "to the existing Authentication Service's verify-token endpoint, so the service holds no JWT secret.")
    para(doc, "All 15 planned customer endpoints are implemented. One customer cannot reach another customer's "
              "data, as verified by 518 automated tests on SQLite and MySQL, a live audit against the Docker "
              "containers with real tokens (73/73) and a Postman collection run with Newman (38/38 assertions). "
              "The flow was also run in the real Swagger UI and captured in 20 screenshots, plus cross-user access denial. The planned admin endpoints were not built.")
    doc.add_heading("Objective", 2)
    para(doc, OBJECTIVE)

    doc.add_heading("2. Requirements status", 1)
    table(doc, ["Requirement", "Status", "Evidence"], [
        ("FastAPI application structure", "Done", "README, folder structure"),
        ("MySQL database connects", "Done", "/health/db connected from the container; MySQL-mode pytest 518 passed"),
        ("SQLAlchemy models", "Done", "05 Database Schema; 17 tests; alembic check clean"),
        ("Alembic migrations", "Done", "2 revisions; head 4f1a9d27c5e3; applied automatically on a fresh volume"),
        ("JWT verification through the Authentication Service", "Done", "57 + 150 tests; live 200/401/503"),
        ("Profile API", "Done", "87 tests; live audit"),
        ("Address API and default address", "Done", "125 tests; live audit; Newman; 300-way concurrency check"),
        ("Account management and deactivation", "Done", "67 tests; live: 403 after deactivation, auth account unchanged"),
        ("Ownership restrictions", "Done", "Security audit test cases 1-20; live cross-user 404s"),
        ("Docker and Docker Compose", "Done", "Both containers healthy; 08 Docker Execution Report"),
        ("Automated tests", "Done", "518 passed on SQLite and MySQL"),
        ("README, reports 01-10, Word documents", "Done", "README.md, DELIVERABELS/"),
        ("Postman testing", "Done (Newman)", "38/38 assertions; not run in the Postman app"),
        ("Admin endpoints", "Not implemented", "Designed in 04"),
        ("Screenshots", "Done", "20 of 20 plus 5 extra; index in screenshots/README.md"),
    ], widths=(5.6, 2.9, 8.1))

    doc.add_heading("3. Implementation details", 1)
    bullets(doc, [
        "Layers: routers (HTTP), services (rules and transactions), models (SQLAlchemy), schemas (Pydantic with "
        "extra fields forbidden).",
        "Identity: auth_user_id is taken only from the Authentication Service's verify response; every query "
        "is filtered by the caller's profile; another user's address gives the same 404 as a missing one.",
        "Default address: transaction plus profile row lock (SELECT ... FOR UPDATE) plus a unique key on a "
        "generated column; deleting the default promotes the oldest remaining address.",
        "Deactivation: sets user_profiles.is_active = 0, keeps all records, blocks every profile, address and "
        "account endpoint with 403, and never calls or changes the Authentication Service.",
        "Errors: JSON only; validation errors never echo values; database and unexpected errors return no "
        "internal details.",
        "Secrets: only the MySQL passwords, from .env (ignored by Git, excluded from the image), masked in logs.",
    ])

    doc.add_heading("4. Database schema", 1)
    table(doc, ["Table", "Key columns and constraints"], [
        ("user_profiles", "id PK; auth_user_id UNIQUE; full_name; phone_number; date_of_birth; gender (CHECK); "
                          "profile_image; is_active; created_at; updated_at"),
        ("user_addresses", "id PK; user_id FK -> user_profiles.id ON DELETE CASCADE; address_type HOME/OFFICE/OTHER "
                           "(CHECK); recipient, address and postal fields; is_default; default_marker (generated) "
                           "with UNIQUE (user_id, default_marker); created_at"),
    ], widths=(3.6, 13.0))

    doc.add_heading("5. API details", 1)
    table(doc, ["Method", "Path", "Success"], [(m, p, s) for m, p, _, s in ENDPOINTS], widths=(1.8, 8.0, 6.8))

    auth_section(doc, "6. Authentication integration")

    doc.add_heading("7. Testing results", 1)
    table(doc, ["Suite", "Passed", "Failed"], [
        ("pytest on SQLite", "518", "0"),
        ("pytest on MySQL", "518", "0"),
        ("of which security audit", "150", "0"),
        ("Live API audit (Docker, real tokens)", "73 checks", "0"),
        ("Postman collection with Newman", "38 assertions", "0"),
        ("Live JWT scenarios", "8", "0 (2 covered only by automated tests, 2 not applicable)"),
    ], widths=(7.6, 3.5, 5.5))

    doc.add_heading("8. Docker execution details", 1)
    table(doc, ["Item", "Configuration"], DOCKER_CONFIG, widths=(4.2, 12.4))
    table(doc, ["Check", "Result"], DOCKER_RESULTS, widths=(5.6, 11.0))
    para(doc, "During the Docker work, the first start crash-looped because Git Bash rewrote API_PREFIX=/api into "
              "a Windows path. The commands were rerun from PowerShell, and API_PREFIX is now validated at "
              "startup (8 tests).")

    doc.add_heading("9. Known limitations", 1)
    bullets(doc, LIMITATIONS)

    doc.add_heading("10. Pending items", 1)
    table(doc, ["Item", "Detail"], PENDING, widths=(6.0, 10.6))

    doc.add_heading("11. Confirmation", 1)
    bullets(doc, [
        "shopease-auth-service and shopease-product-service were not modified. The Authentication Service was "
        "only started with its own Compose file, and test users were registered through its API.",
        "Nothing was committed or pushed to GitHub.",
        ".env is not tracked by Git.",
        "No secret, password or whole token appears in the reports or saved outputs.",
    ])
    return doc


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    documents = {
        "User_Service_Project_Overview.docx": project_overview,
        "User_Service_Database_and_API_Documentation.docx": database_and_api,
        "User_Service_API_Testing_Report.docx": testing_report,
        "User_Service_Final_Completion_Report.docx": final_report,
    }
    for name, build in documents.items():
        path = OUT / name
        build().save(path)
        print(f"wrote {path.relative_to(OUT.parent.parent)} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
