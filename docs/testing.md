# Testing and API Documentation

How ShopEase is tested, how to run each layer, the Postman collection, the OpenAPI checks,
and the results of the last full run. Every layer uses isolated or disposable data: no test
ever touches a database you care about, and payments always use the **mock** provider.

---

## 1. Test layers

| Layer | Where | What it needs | What it covers |
|-------|-------|---------------|----------------|
| **unit** | `<component>/tests/test_models.py`, `test_database.py` | nothing (SQLite in memory / temp files) | Models and constraints, schemas, migrations up/down/up, request-scoped sessions and rollback, settings |
| **api** | `<component>/tests/test_*api.py`, `test_app.py`, `test_proxy.py`, `test_edge.py`, `test_openapi_docs.py` | nothing (FastAPI TestClient; other services replaced by `httpx.MockTransport` fakes; mock payment provider) | HTTP behaviour, status codes, response schemas, error envelopes, auth, ownership, failure handling, OpenAPI documentation |
| **integration (database)** | `<component>/tests/test_mysql_*.py` | a **disposable** MySQL, `SHOPEASE_MYSQL_TESTS=1` | Migrations on real MySQL, schema = models, least-privilege users, cross-database isolation, **stock concurrency** |
| **integration (cross-service)** | `tests/integration/` | Docker; `scripts/run_integration.py` creates and deletes a disposable stack | Full checkout with the mock provider, isolation between users, gateway failures, restarts, parallel checkouts |
| **Postman** | `postman/` | a running stack | The public API from a client's point of view |

Each component's `conftest.py` tags every test with its layer, so one layer can be run alone.

## 2. Running the tests

```bash
python scripts/run_tests.py                     # unit + api, every component (no network, no MySQL)
python scripts/run_tests.py -m unit             # one layer: unit | api | integration
python scripts/run_tests.py --cov               # with line coverage
cd services/order_service && python -m pytest   # one component

# Database integration: a disposable MySQL only (docs/database_setup.md)
SHOPEASE_MYSQL_TESTS=1 SHOPEASE_ALLOW_DESTRUCTIVE_DB_TESTS=1 python scripts/run_tests.py -m integration

# Cross-service integration: builds a separate Compose project `shopease_it` with random
# secrets, its own key, its own volume and ports 18000-18005; removes it all afterwards.
python scripts/run_integration.py
python scripts/run_integration.py --newman path/to/newman   # also run the Postman collection
```

`SHOPEASE_ALLOW_DESTRUCTIVE_DB_TESTS=1` enables migration downgrade tests, which drop tables:
use it only on a throwaway database. Tests are deterministic: no live external service is
called, payments use the in-process mock, and IDs and emails are generated per run.

## 3. Coverage map

| Area | Main tests |
|------|-----------|
| 1. Authentication and token validation | auth `test_auth_api.py` (register, duplicates, login, lockout, refresh rotation + reuse detection, logout, password change, roles, service tokens, 9 bad-token variants); `shared` verifier exercised by every service; gateway `test_edge.py` |
| 2. Profile and address ownership | user `test_users_api.py` (lazy profile, PATCH, address CRUD, cross-user 404, admin read, internal lookup with scope + forwarded token) |
| 3. Product and category validation | product `test_catalog_api.py` (14 invalid-input cases, duplicate SKU, categories incl. cycles and in-use deletes, search escaping, filters, sorting) |
| 4. Inventory concurrency and reservations | product `test_catalog_api.py` (all-or-nothing, replay, confirm/release, expiry, ledger consistency) and `test_mysql_concurrency.py` (30 buyers/10 units, crossed multi-item orders, admin vs reservations, duplicate requests, confirm vs release) on real MySQL |
| 5. Orders, transitions, history | order `test_orders_api.py` (server-side prices, snapshots, idempotency, stock races, timeouts and compensation, payment outcomes, ownership, full transition matrix, recovery job); a fake asserts no DB transaction is open during any network call |
| 6. Payment idempotency and uncertain outcomes | payment `test_payments_api.py` (key reuse, one active payment, amount/currency mismatch, provider amount mismatch, duplicate provider reference, timeout → reconcile, manual review, provider down, automatic refund, card data rejected) |
| 7. Gateway routing, auth, downstream failures | gateway `test_proxy.py`, `test_edge.py`, `test_app.py` (pass-through of methods/headers/query/body/16 status codes, spoofed headers, malformed/leaky responses → 502, timeouts per route, retries only for safe methods, 413, rate limits, CORS) |
| 8. Rollback and validation errors | session rollback unit tests in every service; API tests that force a failure **after rows were flushed** (product, user) and prove nothing persists; 422 envelopes without echoed input everywhere |
| 9. Unauthorized access and isolation | every component's `test_openapi_docs.py` calls every protected operation without a token (401); per-service cross-user tests; `tests/integration/test_isolation.py` end to end |
| 10. Full checkout with the mock provider | `tests/integration/test_checkout.py` (success, out of stock, decline + retry, repeated submissions, uncertain → reconciled, cancellation, refund) |

## 4. Postman

`postman/ShopEase.postman_collection.json` (8 folders, 38 requests, test scripts on every
request) and `postman/ShopEase.local.postman_environment.json` (placeholders only).

1. Import both into Postman, select the environment.
2. Set `adminEmail` / `adminPassword` to an account you registered and promoted
   (`docker compose exec auth_service python -m app.cli promote-admin <email>`).
3. Run the collection in order. A fresh customer is registered on every run.

Tokens and IDs live only in **collection variables** during the run and are cleared by the
last request; the files contain no tokens or real secrets. Folders: health; registration and
login; user operations; catalog setup (admin); browsing; orders; payments (mock); errors and
unauthorized cases (401, 403, 404, 409, 422, declined payment, card data rejected, internal
route blocked, logout).

## 5. Swagger / OpenAPI

Every service serves Swagger UI at `/docs` and the schema at `/openapi.json` (the gateway
documents its own health routes and points to the services). `shopease_shared.openapi`
post-processes each schema so that it matches behaviour:

- a description for the service and every tag; a summary for every operation;
- `bearerAuth` (user token) or `serviceToken` security on protected operations (the
  **Authorize** button), optional security on public routes that show more to admins;
- every error response (`401`, `403`, `404`, `409`, `422`, `default`) refers to the real
  `ErrorResponse` envelope (FastAPI's own `HTTPValidationError` is removed);
- representative request examples on every request body (placeholder data).

`tests/test_openapi_docs.py` in each component checks all of this, and also **calls every
operation documented as protected without a token and expects 401**, so the documentation
can't drift from the behaviour. It found two gaps that are now fixed: the `200` replay of
`POST /internal/reservations` and the `202` of `POST /api/payments` had no response schema.

## 6. Results of the last full run (2026-10-30)

| Layer | Passed | Failed | Skipped | Notes |
|-------|--------|--------|---------|-------|
| unit + api (`run_tests.py`) | **374** (gateway 88, auth 55, user 48, product 63, order 65, payment 55) | 0 | 66 | The skips are the MySQL tests below (65) plus 1 permanent: auth has no external-ID columns, so that parametrized check has no cases |
| integration, database (disposable MySQL 8.0.46) | **65** (12 per service + 5 product concurrency) | 0 | 0 | |
| integration, cross-service (disposable Compose stack) | **54** | 0 | 0 | Stack removed afterwards |
| Postman via Newman 6.2.3 | **38 requests, 122 assertions** | 0 | — | Same disposable stack |

**Not executed in this run:** nothing in the repository was left unexecuted. Not covered by
any automated test: a real payment provider (none exists), webhooks (`501` by design), TLS,
load/performance testing, multiple gateway or service replicas, and the Docker images on a
non-Windows host.

**Line coverage (unit + api only, `--cov`):** gateway 99%, auth 92%, user 97%, product 96%,
order 93%, payment 93%. The largest uncovered parts are the background-job loops in each
`main.py` (exercised by the cross-service suite, which isn't measured), CLI branches in
`auth_service/app/cli.py` (63%) and key-file loading. Coverage is line coverage, not proof
that every behaviour is right.
