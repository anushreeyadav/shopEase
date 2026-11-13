# Daily Teams progress update templates

Copy a template into Teams and fill in the brackets. Keep to facts that have evidence (a log, report or
screenshot). Mark anything not finished as **pending** or **blocked**, with the reason.

## Template: daily update

```
ShopEase Product Catalog Service – Daily update, [date]

Done today
- [task]: [result, e.g. "531 tests passed on MySQL"] (evidence: [file])
- [task]: [result] (evidence: [file])

In progress
- [task]: [what is left]

Blocked
- [item]: [reason] – needs [person/action]

Plan for tomorrow
- [task]
- [task]

Links: README.md, DELIVERABELS/[folder]
```

## Template: blocker message

```
Blocker – ShopEase Product Catalog Service, [date]
What: [e.g. live ADMIN testing of scenarios 1–4, 7–10, 13–18, 20]
Why: [e.g. the Authentication Service has no ADMIN account; it can only be created by a direct database change]
Impact: [e.g. those scenarios are verified on the test instance only]
Needed: [e.g. one ADMIN account and one USER login from the Auth Service owner]
```

## Filled drafts (from the recorded evidence; review before posting)

### Day 1 (Tasks 1–7)

```
ShopEase Product Catalog Service – Day 1 update

Done
- Project set up as an independent FastAPI microservice on port 8006 (own folder, own database).
- Central configuration from environment/.env; no hard-coded passwords or JWT secret.
- SQLAlchemy models for categories, products and inventory_transactions.
- Alembic migration executed on MySQL 8.4.11 (shopease_product_catalog_db); upgrade/downgrade cycle passed on the test database
  (evidence: Test_Results/Migration_Execution_Report.md).
- JWT integration with the existing Auth Service through POST /api/auth/verify-token; 16/16 live checks passed
  (evidence: Test_Results/auth_integration_logs/).
- Category and product APIs with validation, unique SKU, soft delete and ADMIN-only changes
  (evidence: Test_Results/category_api_logs/, product_api_logs/ – 54/54 recorded requests as expected).

Blocked
- Live ADMIN/customer token checks: the Auth Service has no ADMIN account and no login was available.

Next
- Search/filter/paging, inventory, Docker, full API testing.
```

### Day 2 (Tasks 8–12)

```
ShopEase Product Catalog Service – Day 2 update

Done
- Product search, filters, sorting and paging in MySQL; new indexes migration c4a7d2e91b30.
- Inventory: stock-in/stock-out with row locking, full history, low-stock report; rollback and 12-thread tests passed.
- Docker Compose stack (API + MySQL 8.4) with health checks; migrations at start-up; no secrets in the image
  (evidence: DELIVERABELS/Docker_Evidence/).
- API testing: pytest 531 passed (MySQL) / 525 passed + 6 skipped (SQLite); Postman 308 assertions on the test
  instance and 110 on the live stack, 0 failed (evidence: Test_Results/).
- Final audit passed; nine Word documents generated (DELIVERABELS/Word_Documents/).

Pending
- 18 submission screenshots (checklist: DELIVERABELS/screenshots/SCREENSHOT_CHECKLIST.md).

Blocked
- 15 scenarios live (need ADMIN/USER tokens); 3 only partly live (live database empty).
```
