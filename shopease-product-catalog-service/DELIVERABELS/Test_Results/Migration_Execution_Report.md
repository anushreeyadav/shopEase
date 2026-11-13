# Migration Execution Report — ShopEase Product Catalog Service

| | |
|---|---|
| Task | 4 — Configure Alembic database migrations |
| Date | 12 November 2026, approx. 05:20–05:35 UTC |
| Database server | MySQL **8.4.11** (Docker image `mysql:8.4`), `127.0.0.1:3310` |
| Configured database | `shopease_product_catalog_db` (from `.env`) |
| Test database | `shopease_product_catalog_test_db` (throwaway, for downgrade testing) |
| Migration | `5b8e2f0c9d14` — create catalog tables (single head, no parent) |
| Tools | Python 3.11.0, SQLAlchemy 2.1.6, Alembic 1.20.1, PyMySQL 1.2.3 |
| Raw evidence | `DELIVERABELS/Test_Results/migration_logs/` (files 01–10) |

Every result below was produced by a command executed against the MySQL server above. The raw
output of each step is saved in the log file named in the table.

## 1. Summary

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | `alembic.ini` configured | Done. No URL or credentials in the file; date-prefixed file names for new migrations | `alembic.ini` |
| 2 | Alembic uses the central settings | Done. `alembic/env.py` builds the URL from `app.core.config` (`MYSQL_*` / `.env`) | `alembic/env.py` |
| 3 | All models in Alembic metadata | Done. `env.py` imports `app.models`; autogenerate detected all 3 tables | log 02 |
| 4 | Initial migration for the 3 tables | Done. Autogenerate output matches the committed migration (differences are cosmetic only, see §3) | logs 02, 03 |
| 5 | PKs, FKs, unique constraints, indexes, stock constraints | **All present:** 3 PKs, 2 FKs, 2 unique, 5 indexes, 11 CHECK constraints | logs 04, 07, 08 |
| 6 | MySQL 8 compatible | **Executed on MySQL 8.4.11**; CHECK constraints enforced (error 3819) | logs 04, 08 |
| 7 | `alembic upgrade head` applied | **Applied to `shopease_product_catalog_db`**: before = no revision, after = `5b8e2f0c9d14 (head)` | log 06 |
| 8 | All tables created | **Verified**: 3 tables, InnoDB, utf8mb4; `alembic check` reports no differences | logs 07, 08 |
| 9 | Downgrade and upgrade on a safe test database | **Passed** on `shopease_product_catalog_test_db`: upgrade → downgrade to empty → upgrade | log 04 |
| 10 | Commands documented | README.md, section "Database migrations" | `README.md` |
| — | No database with data deleted or reset | **Confirmed**: the existing `shopease_catalog_db` still has 6 / 7 / 7 rows | logs 01, 10 |

## 2. Data safety

The MySQL volume already held a database from earlier development, `shopease_catalog_db`, with
6 categories, 7 products and 7 inventory rows (sample data). To respect "never delete or reset an
existing database containing important data":

- The volume was **not** deleted or reset (`docker compose down -v` was not used).
- The two new databases were **added** with `CREATE DATABASE IF NOT EXISTS`, and the service user
  `catalog_svc` was granted access to them (log 01). Both were checked to be empty first.
- `alembic downgrade` was run **only** on `shopease_product_catalog_test_db`. `alembic/env.py` refuses
  any database other than the service database and this test database, and
  `scripts/migration_check.py` refuses to run its downgrade cycle on anything but the test database.
- After all steps, `shopease_catalog_db` still held 6 / 7 / 7 rows (log 10).
- Only the API container was rebuilt (`--no-deps`); the MySQL container and its volume were left as they were.

## 3. Initial migration: generated and compared

Alembic autogenerate was run against the empty test database, writing into a scratch copy of
the migration folder so the project was not changed (log 02). It detected all three tables and the
indexes `ix_products_category_id`, `ix_products_name` and
`ix_inventory_transactions_product_id_created_at`.

Comparison with the committed migration (log 03) — no schema difference:

| Difference | Why the committed version is kept |
|---|---|
| Autogenerate writes `app.database.types.UTCDateTime()` for timestamps | It does not import that module, so the generated file would fail. The committed file uses `sa.DateTime()`, which creates the same MySQL `DATETIME` column without depending on application code. |
| CHECK constraints in a different order | Order has no effect. |
| `length=3` explicit on `transaction_type` | Same `VARCHAR(3)` either way. |
| Autogenerate drops indexes before tables in `downgrade()` | Dropping a table drops its indexes. |

## 4. Configured database: `alembic upgrade head`

Log 06:

```
== alembic current (before)
(no revision — database not yet migrated)
== alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade  -> 5b8e2f0c9d14, create catalog tables
== alembic current (after)
5b8e2f0c9d14 (head)
```

Read-only verification of the same database (log 07, `python -m scripts.migration_check --verify-only`):

```
[PASS] server is MySQL 8 (8.4.11)
[PASS] tables present: ['categories', 'inventory_transactions', 'products']
[PASS] alembic_version = ['5b8e2f0c9d14']
[PASS] primary keys: 3/3 expected present
[PASS] unique: 2/2 expected present
[PASS] foreign keys: 2/2 expected present
[PASS] checks: 11/11 expected present
[PASS] indexes: 5/5 expected present
[PASS] storage engine InnoDB (required for foreign keys and transactions)
[PASS] alembic check: models and database match
ALL CHECKS PASSED
```

### Schema created (from `SHOW CREATE TABLE`, log 08)

| Table | Primary key | Unique | Foreign key | Indexes | CHECK constraints |
|---|---|---|---|---|---|
| `categories` | `id` | `uq_categories_name` | — | (unique on name) | name not blank |
| `products` | `id` | `uq_products_sku` | `category_id` → `categories.id` ON DELETE RESTRICT | `ix_products_name`, `ix_products_category_id` | price ≥ 0; discount NULL or 0 ≤ discount < price; **stock_quantity ≥ 0**; name and sku not blank |
| `inventory_transactions` | `id` | — | `product_id` → `products.id` ON DELETE RESTRICT | `ix_inventory_transactions_product_id_created_at` | type IN/OUT; quantity > 0; previous and updated stock ≥ 0; **updated = previous ± quantity** |

Columns: `price` and `discount_price` are `decimal(10,2)`; timestamps are `datetime` with
`DEFAULT (now())`, written as UTC (sessions run with `time_zone = '+00:00'`). All tables are
InnoDB with `utf8mb4_0900_ai_ci`.

## 5. Downgrade and upgrade on the test database

`$env:MYSQL_DATABASE="shopease_product_catalog_test_db"; python -m scripts.migration_check` (log 04).
34 checks passed, 0 failed.

```
== alembic upgrade head          -> schema verified (tables, keys, indexes, CHECKs, alembic check)
== alembic downgrade base
INFO  Running downgrade 5b8e2f0c9d14 -> , create catalog tables
[PASS] after downgrade, catalog tables left: []
[PASS] alembic_version is empty after downgrade
== alembic upgrade head (again)
INFO  Running upgrade  -> 5b8e2f0c9d14, create catalog tables
                                 -> schema verified again, alembic check: no differences
```

The script was run twice. In the first run the test database was empty, so all three steps
(upgrade, downgrade, upgrade) executed. Log 04 is the second run, made after the code fix in §6;
there the first upgrade was a no-op because the database was already at head, and the downgrade and
the second upgrade ran as shown.

### MySQL enforces the constraints

Invalid rows were inserted inside one transaction that was then rolled back (no rows left behind):

| Attempt | MySQL response |
|---|---|
| `stock_quantity = -1` | refused, error 3819 (check constraint violated) |
| `discount_price` equal to `price` | refused, 3819 |
| negative `price` | refused, 3819 |
| duplicate SKU | refused, 1062 (duplicate entry) |
| duplicate category name | refused, 1062 |
| product with an unknown category | refused, 1452 (foreign key) |
| transaction type other than IN/OUT | refused, 3819 |
| transaction where updated ≠ previous + quantity | refused, 3819 |
| transaction with quantity 0 | refused, 3819 |
| deleting a category that has products | refused, 1451 (foreign key RESTRICT) |
| server-default `created_at` | equals `UTC_TIMESTAMP()` (UTC confirmed) |

## 6. Issue found and fixed during execution

The first run of the full pytest suite against MySQL (`CATALOG_SERVICE_TEST_DB=mysql`, test database)
gave **15 failed, 161 passed**. All 15 were tests expecting the database to refuse invalid data.
MySQL did refuse it, but **PyMySQL reports a CHECK violation (error 3819) as `OperationalError`**,
the class it uses for outages, not `IntegrityError`.

This was a real defect, not only a test problem: had a CHECK violation ever reached the database,
the API would have answered **503 "Service temporarily unavailable"** instead of a conflict.

Fix:
- `app/database/connection.py`: the engine re-raises MySQL error 3819 as `IntegrityError`
  (query parameters stay hidden).
- `app/main.py`: an `IntegrityError` that reaches the API returns **409** with a generic message.
- Three tests cover this without needing MySQL.

One further test used the value `'MOVE'` (4 characters), which MySQL's strict mode rejects as too
long for `VARCHAR(3)` before the CHECK is evaluated; it now uses a 3-character value so the CHECK is
what refuses it.

After the fix (log 05): **179 passed** on MySQL (test database) and **179 passed** on SQLite.

## 7. Container start-up

The API container was rebuilt from the current code (log 09). On start it ran `alembic upgrade head`
(no change: the database was already at head) and then served on port 8006:

```
GET /health      {"status":"ok","service":"ShopEase Product Catalog Service","version":"1.0.0"}
GET /health/db   {"status":"ok","database":"connected"}
GET /api/products {"items":[],"total":0,"page":1,"size":20,"pages":0}
```

## 8. Notes

- In log 06, the `exit=0` line is the exit status of the output filter, not of Alembic. A note in
  the log says so. Success is shown by `alembic current` reporting `5b8e2f0c9d14 (head)` and by log 07.
- The configured database contains the schema only, no data.
- The old database `shopease_catalog_db` is no longer used by the service. It was left in place
  because it holds data; removing it is a decision for the project owner.

## 9. Reproduce

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d catalog-mysql
.\.venv\Scripts\Activate.ps1
alembic current
alembic upgrade head
python -m scripts.migration_check --verify-only
$env:MYSQL_DATABASE = "shopease_product_catalog_test_db"; python -m scripts.migration_check
$env:CATALOG_SERVICE_TEST_DB = "mysql"; pytest
Remove-Item Env:MYSQL_DATABASE, Env:CATALOG_SERVICE_TEST_DB
```

## 10. Evidence files

| File | Content |
|---|---|
| `01_create_databases.log` | Databases and grants after creating the two new databases |
| `02_autogenerate.log` | Alembic autogenerate run against the empty test database |
| `03_autogenerate_vs_committed.diff` | Difference between generated and committed migration |
| `04_test_db_upgrade_downgrade_cycle.log` | Upgrade / downgrade / upgrade cycle and constraint probes |
| `05_pytest_on_mysql_test_db.log` | Final pytest result on MySQL |
| `06_configured_db_upgrade.log` | `alembic current` / `upgrade head` on the configured database |
| `07_configured_db_verification.log` | Read-only verification of the configured database |
| `08_show_create_table.sql` | `SHOW CREATE TABLE` for the three tables |
| `09_docker_container_startup.log` | Container start-up and health checks |
| `10_old_database_untouched.log` | Row counts of the pre-existing database after all steps |
