# Inventory Management and Transaction History

| | |
|---|---|
| Task | 9: inventory management and transaction history |
| Date | 12 November 2026 |
| Code | `app/services/inventory_service.py` (workflow, locking), `app/models/stock_guard.py` (no stock change without history), `app/routers/inventory_routes.py`, `app/schemas/inventory_schema.py` |
| Tests | `tests/test_inventory_api.py` (86) and `tests/test_inventory_concurrency.py` (4, MySQL): all 90 passed on MySQL 8.4 |
| Evidence | `Test_Results/inventory_logs/02_inventory_transcript.md`: 48 of 48 checks passed |
| Mutation checks | `Test_Results/inventory_logs/03_mutation_checks.log`: each of six deliberate bugs made tests fail |

## 1. Endpoints

All need an ADMIN token: 401 without a valid token, 403 for a customer (`USER`).

| Method | Path | Success | Errors |
|---|---|---|---|
| GET | `/api/inventory/{product_id}` | 200 current stock, threshold, `is_low_stock` | 404 unknown, 422 invalid ID |
| POST | `/api/inventory/{product_id}/stock-in` | 201 `{transaction, stock}` | 404, 409 above the maximum, 422, 400 |
| POST | `/api/inventory/{product_id}/stock-out` | 201 `{transaction, stock}` | 404, 409 insufficient stock, 422, 400 |
| GET | `/api/inventory/{product_id}/history` | 200 every transaction, newest first, in pages | 404, 422 |
| GET | `/api/inventory/low-stock` | 200 active products at or below the threshold, lowest first | — |

Before this task the history was at `/api/inventory/{product_id}/transactions`. It was renamed to
`/history` as specified, without keeping the old path.

## 2. Workflow of one stock movement

```
POST /api/inventory/42/stock-out {"quantity": 3}
  BEGIN
  SELECT ... FROM products WHERE id = 42 FOR UPDATE    -- lock; a second request for product 42 waits here
  (stock 4 - 3 = 1 >= 0, allowed; below 0 -> 409, ROLLBACK, nothing written)
  UPDATE products SET stock_quantity = 1 WHERE id = 42
  INSERT INTO inventory_transactions (OUT, 3, previous 4, updated 1, remarks, created_at)
  COMMIT                                               -- both saved, lock released
  any failure on the way -> ROLLBACK: neither saved, lock released
```

## 3. Requirements

| # | Requirement | How it is met | Evidence |
|---|---|---|---|
| 1 | ADMIN only for stock-in and stock-out | `require_admin` on the whole inventory router (reads too: the history and report are internal) | "Customer cannot stock-in" (403), "Anonymous cannot stock-in" (401), Part B forged token (401); `test_admin_only` |
| 2 | Quantities greater than zero | `quantity` is a strict JSON integer, 1 to 1,000,000,000; the database CHECK `quantity > 0` as well | "Stock-in quantity 0 / -2 / 1.5 / '3'" (422); `test_invalid_quantities_are_422` (18 cases) |
| 3 | Current stock | `GET /api/inventory/{id}` | "Current stock"; `test_current_stock` |
| 4 | Stock-in increases | `stock_quantity += quantity` | "Stock-in 5" (10 → 15); `test_stock_in`, `test_repeated_stock_in_accumulates` |
| 5 | Stock-out decreases | `stock_quantity -= quantity` | "Stock-out 3" (15 → 12); `test_stock_out`, `test_stock_out_to_exactly_zero` |
| 6 | Never negative | Checked against the locked row; database CHECK `stock_quantity >= 0` | "Stock-out 5 with 4 available" (409, stock still 4); `test_insufficient_stock_changes_nothing` |
| 7 | Every change recorded | Stock is changed only by `record_movement`, which adds the row; the stock guard refuses any other change | `test_direct_stock_change_is_refused`, `test_product_updates_never_change_stock` |
| 8 | Type, quantity, previous, updated, remarks, timestamp | Columns of `inventory_transactions`; `created_at` in UTC | Every movement response in the transcript |
| 9 | Stock and record in one transaction | One `COMMIT` for both | §2 |
| 10 | Roll back both if either fails | Explicit `ROLLBACK` on any failure | "Stock-in 50 while the history insert fails" (503, stock unchanged); `test_failure_of_either_write_rolls_back_both` (8 cases), `test_nothing_is_kept_after_a_failed_movement`, `test_failure_at_commit_keeps_nothing` |
| 11 | Concurrency protection | `SELECT ... FOR UPDATE` on the product row for the whole transaction | `test_inventory_concurrency.py`; with the lock removed all 4 tests fail (mutation log) |
| 12 | `LOW_STOCK_THRESHOLD` | Setting, default 5, read from the environment or `.env` | `test_low_stock_threshold_comes_from_the_setting` (10, then 0) |
| 13 | Stock at or below the threshold | `stock_quantity <= threshold`, active products | "Low-stock report" (stock 5, threshold 5: listed; after +20: gone); `test_low_stock_report` |
| 14 | Complete history | Every transaction including initial stock; `total` plus pages that together return all | "Complete history" (5 transactions); `test_history_pages_together_return_everything` |
| 15 | Invalid IDs and insufficient stock | 422 for `0`, `-1`, `abc`, `1.5`, `2^31`; 404 for an unknown product; 409 `Insufficient stock: N available, M requested` | "Unknown product: …" (404), "Invalid product ID …" (422); `test_unknown_product_is_404`, `test_invalid_product_id_is_422` |

## 4. Initial stock and product updates

- **Initial stock** (`initial_stock` on `POST /api/products/`): the product is inserted with
  stock 0, then the stock is recorded as an IN transaction (`previous_stock` 0, remarks
  `Initial stock`). Both are in the product's create transaction. `initial_stock` 0, or left
  out, records nothing. A refused product (for example a duplicate SKU) leaves no transaction.
  So the history of every product starts at 0, and replaying it always gives the current stock.
- **Product updates** (POST, PUT, PATCH) refuse `stock_quantity` with 422 and never change stock.
- **Stock guard** (`app/models/stock_guard.py`). Before every database write by the application,
  it checks each product whose `stock_quantity` changes. The change must be matched by new
  transaction rows that lead from the old value to the new one, and a new product must start at 0.
  Otherwise the write is refused and rolled back. This turns a future programming mistake (an
  endpoint that sets stock directly) into an error instead of an unrecorded change.
- **Limit:** a manual SQL `UPDATE` run directly on the database bypasses the guard. Stock
  corrections must be made with stock-in or stock-out.

## 5. Design decisions

| Decision | Reason |
|---|---|
| Reads (stock, history, low-stock) are ADMIN only too | The task requires ADMIN for movements. The history and the report are internal stock records; customers see `stock_quantity` and `in_stock` on the product endpoints |
| History is paged (`page_size` up to 100) with `total` | A product's history grows without limit. Every transaction is returned across the pages, and `total` says how many there are |
| Strict integer quantity | `"5"`, `5.0` and `true` would otherwise be converted silently. For stock counts, an exact whole number is safer |
| Insufficient stock is 409 and names the available quantity | The request is valid but conflicts with the current state. Only admins can call it, so the number reveals nothing to customers |
| A database refusal during a movement is 409, a lost database 503 | Same mapping as the rest of the API, and no driver text in the response |
| Inactive products can still receive and release stock | Deactivation hides a product from sale; the goods may still be in the warehouse |
| Inactive products are not in the low-stock report | They are not being sold, so they need no reorder |
| The lock is on the product row, not the table | Movements of different products never wait for each other |

## 6. Tests

- **Stock-in and stock-out:** fields, remarks, accumulation, down to exactly 0, the maximum, and
  inactive products.
- **Insufficient stock:** 2 → 3, 0 → 1, 5 → 1,000,000. Each time stock and history are unchanged,
  and a correct stock-out still works afterwards.
- **Zero, negative and invalid quantities:** 9 values, for both stock-in and stock-out. Also
  unknown fields (`transaction_type`, `previous_stock`, `updated_stock`) and malformed JSON (400).
- **History:** completeness, newest first, pages, type filter, per product, and kept after
  deactivation.
- **Low stock:** the boundary (5 is listed, 6 is not), lowest first, inactive products left out,
  and the threshold changed through `LOW_STOCK_THRESHOLD` (10, then 0).
- **Rollback:** a failure is injected at the database level. It hits the product `UPDATE` or the
  history `INSERT`, as an outage (503) or a refusal (409), for stock-in and stock-out, and also
  at `COMMIT` after both writes were sent. Each time a fresh read shows the stock and the history
  unchanged, and the next movement succeeds (the lock was released).
- **Simultaneous updates** (MySQL; separate connections, real commits, released together by a
  barrier):
  - 12 stock-outs of 1 with stock 5: exactly 5 succeed, 7 get `Insufficient stock`, stock ends at 0.
  - 12 stock-ins of 3: none lost (10 → 46).
  - 6 stock-ins and 6 stock-outs mixed.
  - 12 stock-outs of 2 through HTTP with the real per-request sessions: 10 × 201, 2 × 409.

  Each run ends with a consistency check. The history, in commit order, must be one unbroken
  chain from 0 to the current stock.
- **Consistency:** every API test that changes stock ends by replaying the whole history through
  the API and comparing it with the current stock.
- **Mutation checks** (`scripts/inventory_mutation_check.py`). Six deliberate bugs were introduced
  one at a time, and each made tests fail:
  - no `FOR UPDATE` (all 4 concurrency tests fail);
  - no rollback on failure;
  - no rollback on a database refusal;
  - stock guard disabled;
  - low stock strictly below the threshold;
  - overdraw by one allowed.

  The code was restored after each one. The first run showed that "no rollback on refusal" went
  unnoticed, so the rollback test was extended to database refusals; it is now caught.

## 7. Evidence

`python -m scripts.inventory_evidence` writes the transcript.

- **Part A (36 HTTP steps, 6 content checks).** The real application with the real MySQL 8.4 test
  database, inside one transaction that was rolled back. A check after the run found no rows
  left. The Authentication Service is a stand-in, because the live one has no ADMIN account.
  - **The run:**
    - initial stock 10;
    - +5;
    - −3;
    - −8;
    - a refused −5;
    - invalid quantities;
    - unknown and invalid IDs;
    - access checks.
  - **The injected failure:** a stock-in of 50 whose history `INSERT` fails. The answer is 503,
    and the stock stays 4.
  - **History and low stock:** +1, the history, and the low-stock report before and after +20.
  - **The final check:** the history replays 0 → 10 → 15 → 12 → 4 → 5 → 25, equal to the
    current stock.
- **Part B (6 HTTP steps).** The running container with the real Authentication Service. Each
  endpoint without a token, and a forged ADMIN token, answer 401.
- **Simultaneous requests** cannot be shown inside one rolled-back transaction. They are recorded
  in `01_pytest_inventory.log` (`test_inventory_concurrency.py`, run against MySQL with real
  commits; each test deletes its own rows afterwards, and a check found none left).

## 8. Results

| Run | Result |
|---|---|
| `test_inventory_api.py` + `test_inventory_concurrency.py`, MySQL 8.4 test database | 90 passed |
| Whole suite, MySQL 8.4 test database | 481 passed |
| Whole suite, SQLite | 476 passed, 5 skipped (4 concurrency tests and 1 MySQL-only test need MySQL) |
| Inventory transcript | 48 of 48 checks passed |
| Mutation checks | 6 of 6 deliberate bugs detected |

Logs: `Test_Results/inventory_logs/01_pytest_inventory.log`, `02_inventory_transcript.md`,
`03_mutation_checks.log`.
