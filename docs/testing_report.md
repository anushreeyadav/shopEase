# Testing Report — Final Submission

Commands executed and their actual results for the final audit on **2026-10-30**, on
Windows 11 Pro with Python 3.14.7, Docker Engine 29.6.2 (Compose v5.3.1), MySQL 8.0.46
(disposable instance) and MySQL 8.4 (container). How the layers work and how to run them:
[testing.md](testing.md).

Every run used isolated data: SQLite in memory or temp files, a throwaway MySQL instance
deleted afterwards, and a separate Docker Compose project removed with `down -v`. No test
touched the development database or the machine's own MySQL service. Payments used the
in-process **mock** provider only.

---

## 1. Summary

| # | Layer | Command | Passed | Failed | Skipped |
|---|-------|---------|-------:|-------:|--------:|
| 1 | Unit + API (all 6 components, with coverage) | `python scripts/run_tests.py --cov` | **374** | 0 | 66 |
| 2 | Database integration (disposable MySQL 8.0.46) | `SHOPEASE_MYSQL_TESTS=1 SHOPEASE_ALLOW_DESTRUCTIVE_DB_TESTS=1 python scripts/run_tests.py -m integration` | **65** | 0 | 0 |
| 3 | Cross-service integration (disposable Compose stack) | `python scripts/run_integration.py --newman <newman>` | **54** | 0 | 0 |
| 4 | Postman collection via Newman 6.2.3 (same stack) | *(run by the command above)* | **38 requests, 122 assertions** | 0 | — |
| 5 | Static checks | `docker compose config --quiet`; Mermaid parser on 9 diagram sources; repository audit | valid; 9/9 parse; see §5 | — | — |

**Skipped in run 1 (66):** 65 are the database integration tests, which need MySQL and were
executed in run 2. The remaining 1 is permanent by design: auth_service stores no IDs owned
by other services, so its "external IDs are indexed" check has no cases.
**Not executed:** none of the repository's tests (440 collected in the components, 54 in
`tests/integration/`).

## 2. Unit + API tests (run 1)

| Component | Collected | Passed | Skipped (needs MySQL / by design) | Line coverage |
|-----------|----------:|-------:|----------------------------------:|--------------:|
| api_gateway | 88 | 88 | 0 | 99% |
| auth_service | 68 | 55 | 12 + 1 | 92% |
| user_service | 60 | 48 | 12 | 97% |
| product_service | 80 | 63 | 17 | 96% |
| order_service | 77 | 65 | 12 | 93% |
| payment_service | 67 | 55 | 12 | 93% |
| **Total** | **440** | **374** | **66** | — |

Coverage is line coverage of each component's `app` package from unit + API tests only.
Least covered: the background-job loops in each `main.py` (run by the cross-service suite,
which is not measured), `auth_service/app/cli.py` (63%), and key-file loading.

## 3. Database integration (run 2)

| Component | Passed | What it proves on real MySQL |
|-----------|-------:|------------------------------|
| auth_service | 12 | Migrations apply twice cleanly, live schema = models (incl. types), downgrade/upgrade, runtime user can't change the schema, no access to the other 4 databases |
| user_service | 12 | Same |
| product_service | 17 | Same, plus 5 concurrency tests: 30 buyers for 10 units (10 succeed), crossed multi-item orders, admin removals racing reservations, 8 duplicate requests for one order, confirm racing release; stock never negative and the audit ledger adds up |
| order_service | 12 | Same as auth |
| payment_service | 12 | Same as auth |

## 4. Cross-service integration and Postman (runs 3–4)

`scripts/run_integration.py` built all images, started the separate project `shopease_it`
(own secrets, key, volume, ports 18000–18005), waited until healthy, ran the suite, ran
Newman, then removed everything.

| File | Passed | Scenarios |
|------|-------:|-----------|
| `test_smoke.py` | 22 | Liveness, readiness + database, OpenAPI served for all 6 components; public routes; `/internal/*` blocked |
| `test_checkout.py` | 7 | Full checkout with the mock provider (order → payment → `PAID`, stock deducted); out of stock; decline then retry; repeated submissions (one order, one charge); uncertain payment reconciled to `SUCCEEDED`; cancellation returns stock and blocks payment; admin refund cancels the order |
| `test_isolation.py` | 22 | Other customers see none of my orders/payments/addresses; paying someone else's order refused; customers can't use admin operations; 18 unauthenticated / garbage-token / spoofed-header requests rejected; refresh token dead after logout |
| `test_concurrency_and_resilience.py` | 3 | 8 parallel checkouts for 3 units (exactly 3 succeed); stopped product_service degrades to `503` and recovers; restarted order_service keeps checkout working |

Newman: 8 folders, 38 requests, 76 test scripts, **122 assertions, 0 failures** (registration
and login, user operations, admin catalog setup, browsing, orders, mock payments, and error
cases: 401, 403, 404, 409, 422, declined payment, card number rejected, internal route
blocked, refresh after logout).

## 5. Audit checks (2026-10-30)

| Check | Result |
|-------|--------|
| Six entry points (`app/main.py` exposing `app`) import and build their OpenAPI | 6/6 |
| No component references another service's database (env prefixes, database names, imports) | 5/5 services clean; one hit in user_service was a docstring stating there is *no* foreign key to `auth_db` |
| Gateway has no database code | clean |
| Operations without a required token are exactly the intended public ones | register, login, refresh, JWKS, service-token exchange (client credentials), catalog reads, payment webhook stub (`501`) |
| `payment_db` and payment schemas hold no card number, CVV, PIN, expiry or secret | clean (brand, last four and provider references only) |
| Secret scan of the 233 files to be committed (private keys, JWTs, AWS keys, assigned secrets) | no real secrets; flagged items reviewed: test-only placeholder passwords, a fake service token in a test double, and the public test card number `4111…` used to prove card data is rejected |
| `.env`, `secrets/`, keys, `.venv`, caches, coverage files, databases, logs excluded from Git | verified with `git check-ignore` and the staged file list |
| `.env.example` and the Postman environment hold placeholders only | clean |
| `docker compose config --quiet` | valid |
| Mermaid diagrams | 9/9 parse; embedded copies identical to their `.mmd` sources |

## 6. Not covered by automated tests

A real payment provider (none implemented), provider webhooks (`501`), TLS, load and
performance testing, multiple replicas of a service, the containers on a non-Windows Docker
host, and an independent security review.
