# Product Search, Filtering, Pagination and Sorting

| | |
|---|---|
| Task | 8: search, filters, pagination and sorting on `GET /api/products/` |
| Date | 12 November 2026 |
| Code | `app/schemas/product_schema.py` (`ProductListQuery`), `app/schemas/common_schema.py` (`PageQuery`, `Page`), `app/services/product_service.py` (`list_products`), `app/routers/product_routes.py` |
| Migration | `alembic/versions/c4a7d2e91b30_add_product_listing_indexes.py`: indexes on `products.price` and `products.created_at` |
| Tests | `tests/test_product_search.py`: 62 tests, all passed on SQLite and on MySQL 8.4. Two of them request all 375 filter combinations each |
| Evidence | `Test_Results/product_search_logs/02_search_transcript.md`: 85 of 85 checks passed |
| OpenAPI export | `API_Documentation/openapi.json`, taken from the running container after this change |

## 1. Query parameters

| Parameter | Values | Meaning |
|---|---|---|
| `search` | 1–100 characters | Part of the name or SKU, ignoring case. Surrounding spaces ignored; `%` and `_` match themselves |
| `category_id` | positive integer | Only this category |
| `min_price`, `max_price` | decimal ≥ 0, 2 places | Inclusive range on the normal price; `max_price` must not be below `min_price` |
| `availability` | `in_stock`, `out_of_stock` | Stock above 0, or stock 0 |
| `brand` | 1–100 characters | Exact brand, ignoring case (kept from Task 7) |
| `page` | 1–100000, default 1 | Page number |
| `page_size` | 1–100, default 20 | Items per page |
| `sort_by` | `name` (default), `price`, `created_at` | Sort column |
| `sort_order` | `asc` (default), `desc` | Direction |
| `include_inactive` | `true`, `false` | ADMIN only: inactive products too |

Response: `{"items": [...], "total": 23, "page": 2, "page_size": 5, "total_pages": 5}`.

The task's examples, all recorded in the transcript:

```
GET /api/products/?search=mobile
GET /api/products/?category_id=1
GET /api/products/?min_price=1000&max_price=5000
GET /api/products/?page=1&page_size=10
GET /api/products/?sort_by=price&sort_order=asc
```

## 2. Requirements

| # | Requirement | How it is met | Evidence |
|---|---|---|---|
| 1 | Search by name and SKU | Case-insensitive substring match on either column; wildcards escaped | "search=mobile" returns Laptop Stand through its SKU only; `test_search_matches_name_or_sku_ignoring_case`, `test_search_treats_wildcards_literally` |
| 2 | Filter by category | `category_id` | "category_id"; `test_filter_by_category` |
| 3 | Minimum and maximum price | Both inclusive, on `price` | "min_price=1000&max_price=5000" includes 1000.00 and 5000.00 and leaves out 5000.01; `test_price_range_is_inclusive` |
| 4 | Stock availability | `availability=in_stock` / `out_of_stock` | "availability=…"; `test_filter_by_availability`, `test_stock_changes_move_a_product_between_availability_filters` |
| 5 | Pagination | `page`, `page_size` | "Page 1 of 3", "Page 3 of 3"; `test_pages_cover_every_product_exactly_once` |
| 6 | Ascending and descending sorting | `sort_order` | `test_sorting` (6 cases) |
| 7 | Safe sorting on approved columns only | `sort_by` accepts only `name`, `price`, `created_at`. It selects a column from a fixed mapping in the service; request text never reaches the SQL | "sort_by not allowed" (Part B, `id; DROP TABLE products`) → 422; SQL in the transcript |
| 8 | Validate query parameters | One Pydantic model for all parameters; unknown parameters are refused too | `test_invalid_query_parameters_are_422` (26 cases) |
| 9 | No negative pages or invalid page sizes | `page` ≥ 1; `page_size` 1–100 | "page=0", "page=-1", "page_size=101" → 422 |
| 10 | Total records, current page, page size, total pages | `total`, `page`, `page_size`, `total_pages` | `test_page_metadata`, `test_page_past_the_end_is_empty_with_correct_totals` |
| 11 | Customer visibility rules on every result | The visibility condition is part of the same WHERE clause as every filter, and of the COUNT | "Customer searches for the inactive product's exact SKU" → empty; `test_every_filter_combination[customer]` |
| 12 | Filtering and paging in the database | One `COUNT` query and one `SELECT … ORDER BY … LIMIT` query per request | SQL recorded in the transcript; `test_filtering_and_paging_happen_in_the_database`, `test_only_one_page_of_rows_is_fetched` |

## 3. Validation

Every invalid value gets 422 with the field and the reason, for example:

| Request | Response `errors` |
|---|---|
| `?page=0` | `page`: Input should be greater than or equal to 1 |
| `?page_size=101` | `page_size`: Input should be less than or equal to 100 |
| `?sort_by=id; DROP TABLE products` | `sort_by`: Input should be 'name', 'price' or 'created_at' |
| `?sort_order=up` | `sort_order`: Input should be 'asc' or 'desc' |
| `?availability=maybe` | `availability`: Input should be 'in_stock' or 'out_of_stock' |
| `?min_price=-1` | `min_price`: Input should be greater than or equal to 0 |
| `?min_price=50&max_price=10` | `max_price`: max_price must not be lower than min_price |
| `?size=10` | `size`: Unknown query parameter |

Several invalid parameters are reported together in one response.

## 4. Design decisions

| Decision | Reason |
|---|---|
| Parameter and field names follow the task (`page_size`, `sort_by`, `sort_order`, `availability`, `total_pages`) | The Task 7 names (`size`, `sort`, `order`, `in_stock`, `pages`) were replaced, not kept as aliases. The service has no external clients yet, and two names for one setting invite mistakes. The inventory history list uses the same paging names and fields |
| Unknown query parameters get 422 | Otherwise an old or misspelt name such as `size=10` would be silently ignored, and the caller would get 20 items without knowing why |
| The price filter and price sort use `price`, not `discount_price` | The task names `price`; the list price is indexed and needs no calculated column. A product at 100.00 discounted to 40.00 is not found by `max_price=50`. If the customer should filter on what they pay, the filter can be moved to `effective_price` (it would need a calculated, indexed column) |
| Ties are broken by ID in the requested direction | Products with the same name, price or creation second keep a fixed order, so pages never repeat or skip one, and "newest first" stays newest first within the same second |
| A page past the last one returns 200 with no items | The page is valid; nothing is on it. `total` and `total_pages` tell the client where the last page is |
| An unknown or inactive category gives an empty list, not 404 or 422 | The list is filtered, not the category looked up. It also reveals nothing about inactive categories |
| Two new indexes (`price`, `created_at`) | The price filter and both new sorts would otherwise scan the table. MySQL's EXPLAIN for a price range sorted by price uses `ix_products_price` |

## 5. How it was tested

`tests/test_product_search.py` builds one catalogue through the API. It has eight products in
three categories:
- a product found only through its SKU;
- prices exactly on the 1000 and 5000 boundaries and one cent above;
- stock 0;
- an inactive product;
- an active product in an inactive category.

- **All filter combinations.** 5 searches × 5 categories (including missing and inactive) × 5
  price ranges × 3 availabilities = 375 requests. They are run once as a customer and once as an
  admin with `include_inactive`. Each response is compared with a plain-Python reference
  implementation of the documented rules: the exact SKUs, their order, and `total`. The six sort
  orders are rotated through the grid. A guard test checks that the grid produces empty, single
  and multiple results.
- **Anonymous visitors**: the same 375 requests, checking that no hidden product appears.
- **Sorting, paging and validation**, each tested on its own, plus checks on the SQL actually sent.
- **The tests can fail.** Six deliberate bugs were introduced one at a time in the service, and
  each made at least one test fail:
  - minimum price made exclusive;
  - tie-break always ascending;
  - visibility rule removed;
  - visibility removed from the count only;
  - SKU not searched;
  - `out_of_stock` ignored.

  The service was restored afterwards.

## 6. How the evidence was produced

`python -m scripts.product_search_evidence` writes the transcript.

- **Part A (24 HTTP steps, 39 content checks).**
  - The real application with the real MySQL 8.4 test database, inside one transaction that was
    rolled back.
  - The same kind of catalogue is created first, so each listing is checked against the exact
    SKUs expected, in order, and against `total`.
  - It includes the SQL MySQL received for one combined request:
    - search, price, stock and both visibility conditions are in the WHERE clause of both the
      COUNT and the page query;
    - the page query ends `ORDER BY products.price DESC, products.id DESC LIMIT %(param_1)s, %(param_2)s`,
      with offset 0 and row count 2;
    - the request values are sent as bound parameters.
  - A check after the run found none of the rows in the test database.
  - The Authentication Service is a stand-in, because the live one has no ADMIN account.
- **Part B (15 HTTP steps, 7 consistency checks).**
  - The running container with its configured database and the real Authentication Service.
    Read-only, as an anonymous visitor.
  - **The configured database `shopease_product_catalog_db` holds no products at present.** So the
    task's example requests are shown answering 200 with correct paging fields, but empty lists.
    The filtering itself is shown in Part A.
  - The invalid requests are shown refused with 422, and `include_inactive` without a token with 401.

## 7. Migration

`c4a7d2e91b30` adds `ix_products_price` and `ix_products_created_at`; it changes no data, and its
downgrade drops only those two indexes. It was applied to the configured database
`shopease_product_catalog_db`, when the rebuilt container ran `alembic upgrade head` (log:
`Running upgrade 5b8e2f0c9d14 -> c4a7d2e91b30`). A query afterwards showed `alembic_version` =
`c4a7d2e91b30` and both indexes present. `tests/test_migrations.py` runs the migrations on a
private SQLite database and found no difference between the models and the migrated schema.

**Correction (recorded during Task 10, 12 November 2026).** An earlier version of this report also
said that the MySQL test run applied the migration to `shopease_product_catalog_test_db`. That was
wrong: the test suite does not run migrations on MySQL, and that database was still at
`5b8e2f0c9d14` during the Task 8 test runs (the tests pass without the two indexes). The migration
was then applied to it with `alembic upgrade head`. `alembic check` against both MySQL databases
reported `No new upgrade operations detected` (log:
`Test_Results/migration_logs/task8_listing_indexes_mysql.log`).

## 8. Results

| Run | Result |
|---|---|
| `tests/test_product_search.py`, MySQL 8.4 test database | 62 passed |
| `tests/test_product_search.py`, SQLite | 62 passed |
| Whole suite, MySQL 8.4 test database | 401 passed |
| Whole suite, SQLite | 400 passed, 1 skipped (a MySQL-only test) |
| Search transcript | 85 of 85 checks passed |
| Product API transcript (Task 7), recorded again | 54 of 54 steps as expected |

Logs: `Test_Results/product_search_logs/01_pytest_product_search.log` and `02_search_transcript.md`.
