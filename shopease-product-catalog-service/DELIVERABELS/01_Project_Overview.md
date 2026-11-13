# ShopEase Product Catalog Service — Project Overview

| | |
|---|---|
| Service | ShopEase Product Catalog Service |
| Version | 1.0.0 |
| Location | `C:\Users\Administrator\ShopEase\shopease-product-catalog-service` |
| Framework | FastAPI on Python 3.11 |
| Database | MySQL 8.4 (`shopease_product_catalog_db`), managed by Alembic migrations |
| API port | 8006 (`SERVICE_PORT`) |
| Document date | 12 November 2026 |

## 1. Purpose

The Product Catalog Service is an independent microservice that extends the ShopEase
e-commerce platform. It owns the catalog data: **product categories**, **products**, and
**inventory (stock levels)**.

It is a separate project from the earlier ShopEase Product Service (port 8003). The two
services share no code and no database, and the earlier service has not been changed.

## 2. Place in the ShopEase architecture

| Service | Port | Database (host port) | Responsibility |
|---|---|---|---|
| API Gateway (main platform) | 8000 | — | Routes requests to the platform services |
| Authentication Service | 8001 | MySQL (3308) | Registration, login, JWT tokens, token verification |
| User Service | 8002 | MySQL (3309) | User profiles and addresses |
| Product Service (earlier) | 8003 | none (in-memory) | Original product prototype |
| Order Service (main platform) | 8004 | MySQL (3306) | Orders |
| Payment Service (main platform) | 8005 | MySQL (3306) | Payments |
| **Product Catalog Service** | **8006** | **MySQL (3310)** | **Categories, products, inventory** |

Port 8006 was chosen because 8000–8005 are already used. The service refuses to start on any of
those ports (see `RESERVED_SHOPEASE_PORTS` in `app/core/config.py`).

Each service has its own database. The Catalog Service does not store users or passwords and
holds no JWT secret. For admin requests it sends the caller's token to the Authentication
Service (`POST /api/auth/verify-token`) and uses the role that service returns.

## 3. Scope

| Area | Included |
|---|---|
| Service endpoints | `GET /health`, `GET /health/db`, Swagger UI at `/docs`, ReDoc at `/redoc` |
| Categories | Create, list, view, update, deactivate; delete only when empty |
| Products | Create, list with pages, search, filters and sorting; view, update, deactivate |
| Inventory | Stock in and stock out with a full transaction history; low-stock report |
| Access control | Public browsing; `ADMIN` role required for every change and for inventory |

## 4. Technology stack

| Component | Choice |
|---|---|
| Language | Python 3.11 |
| Web framework | FastAPI 0.162, Uvicorn 0.54 |
| Validation and settings | Pydantic 2.14, pydantic-settings 2.16 |
| Database access | SQLAlchemy 2.1, PyMySQL 1.2 |
| Migrations | Alembic 1.20 |
| Environment files | python-dotenv 1.2 |
| JWT library | python-jose 3.5 (same as the Authentication Service; format pre-check only) |
| HTTP client (Authentication Service) | httpx 0.28 |
| Testing | pytest 9.2 |
| Containers | Docker, Docker Compose (MySQL 8.4 image) |

## 5. Project structure

```
shopease-product-catalog-service/
├── app/
│   ├── main.py              Application setup, routes, error handlers, health endpoints
│   ├── core/                Configuration and security
│   ├── database/            Database connection and sessions
│   ├── models/              Database tables (ORM models)
│   ├── schemas/             Request and response formats
│   ├── services/            Business rules
│   └── routers/             API endpoints
├── alembic/                 Database migrations
├── tests/                   Automated tests
├── postman/                 Postman collection for manual API testing
├── scripts/                 Helper scripts (sample data)
├── DELIVERABELS/            Project documents and evidence
├── alembic.ini, requirements.txt, .env.example, .gitignore
└── Dockerfile, docker-compose.yml, docker-compose.dev.yml, README.md
```

| Folder | Purpose |
|---|---|
| `app/routers` | Defines the HTTP endpoints. Only handles requests and responses; no business rules. |
| `app/models` | Describes the database tables: `categories`, `products`, `inventory_transactions`. |
| `app/schemas` | Defines and validates what clients send and receive (for example, price format, SKU format). |
| `app/services` | Holds the business rules, such as "stock out cannot exceed the current stock". |
| `app/core` | Settings loaded from `.env`, and token checking through the Authentication Service. |
| `app/database` | Declarative base, UTC timestamp type, database connection and session management. |
| `alembic` | Versioned scripts that create and change the database tables. |
| `tests` | Automated tests that check every endpoint and rule. |
| `postman` | Generates a Postman collection and environment for manual testing. |
| `scripts` | Developer helpers, such as loading sample categories and products. |
| `DELIVERABELS` | Reports, screenshots and evidence for the project submission. |

## 6. Data model

Database `shopease_product_catalog_db` on MySQL 8, created only by Alembic migrations:
`5b8e2f0c9d14_create_catalog_tables`, then `c4a7d2e91b30_add_product_listing_indexes` (Task 8).

| Table | Columns | Rules enforced by the database |
|---|---|---|
| `categories` | id, name, description, is_active, created_at, updated_at | Name unique and not blank |
| `products` | id, category_id, name, description, sku, price, discount_price, stock_quantity, image_url, brand, is_active, created_at, updated_at | SKU unique; category must exist; price ≥ 0; discount below price; stock never negative |
| `inventory_transactions` | id, product_id, transaction_type, quantity, previous_stock, updated_stock, remarks, created_at | Type IN or OUT; quantity > 0; updated stock = previous stock ± quantity |

- **Relationships:** one category has many products; one product has many inventory transactions.
  A category with products, or a product with history, cannot be deleted (ON DELETE RESTRICT).
- **Indexes:** product name, SKU (unique), category ID, and (product_id, created_at) for history.
- **Money:** `DECIMAL(10, 2)`, handled as Python `Decimal`, never floating point.
- **Time:** every timestamp is stored and returned in UTC.
- **Stock:** `stock_quantity` changes only through IN/OUT transactions, so each change is recorded.

## 7. Security approach

- Browsing active categories and products needs no login.
- Every change, and every inventory endpoint, requires a valid token whose user has the
  `ADMIN` role in the Authentication Service.
- If the Authentication Service cannot be reached, requests that need a login are refused (503).
- Passwords come from `.env`, which is excluded from Git and from the Docker image.
- Error responses do not repeat submitted values or internal details.

## 8. Development phases

| Phase | Task | Status |
|---|---|---|
| 1 | Initialise project structure, FastAPI app, health endpoint, Swagger docs | Complete |
| 2 | Dependencies and centralised configuration (`app/core/config.py`) | Complete |
| 3 | Database layer: SQLAlchemy models and constraints | Complete |
| 4 | Alembic migrations applied and verified on MySQL 8.4 | Complete (see `Test_Results/Migration_Execution_Report.md`) |
| 5 | Category, product and inventory APIs | Complete: categories (Task 6), products (Task 7), product search, filters, paging and sorting (Task 8), inventory and transaction history (Task 9) |
| 6 | Authentication Service integration | Complete; live check run without real-account logins (see `02_JWT_Integration.md`) |
| 7 | Testing, Postman, Docker evidence, final reports | Complete: Docker (Task 10), API testing (Task 11), final audit and Word documents (Task 12). Screenshots: all 18 captured. Blocked: live ADMIN testing (see `Final_Completion_Checklist.md`) |

## 9. How to run

```powershell
cd C:\Users\Administrator\ShopEase\shopease-product-catalog-service
Copy-Item .env.example .env          # first time only; replace every change-me value
docker compose up --build -d         # MySQL + API; waits for MySQL, migrations run automatically
```

Then open http://127.0.0.1:8006/docs.

Without Docker, for the API only:

```powershell
py -3.11 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app                        # 127.0.0.1:8006 by default
```

## 10. Deliverables folder

| Folder | Intended contents |
|---|---|
| `Word_Documents` | Final reports in Word format |
| `screenshots` | Screenshots of Swagger UI, Docker, MySQL and API responses |
| `Test_Results` | pytest and Postman run outputs |
| `API_Documentation` | Endpoint reference and OpenAPI export |
| `Database_Evidence` | Migration logs and table structure |
| `Docker_Evidence` | Container status and logs |
| `Progress_Reports` | Daily and task progress reports |

All folders now hold their evidence: `Word_Documents` (nine reports), `Test_Results` (pytest logs, Postman
reports, transcripts, final audit), `API_Documentation` (OpenAPI and endpoint reference), `Database_Evidence`
(schema SQL reference), `Docker_Evidence`, `Progress_Reports` (Teams templates) and `screenshots` (14 automated
Swagger UI screenshots, and the 18 submission screenshots in `screenshots/submission/`, all captured on 13 November
2026 and collected in `screenshots/ShopEase_Submission_Screenshots.pptx`).
