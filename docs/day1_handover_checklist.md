# Day 1 → Day 2 Handover Checklist

For whoever starts the Day 2 implementation. Day 1 produced **documentation only**: no
services, models, migrations or Docker deployment were built on Day 1.

Start with [shopease_architecture.md](shopease_architecture.md), then
[rest_api_notes.md](rest_api_notes.md) for the exact contracts.

---

## A. Decisions to confirm before coding (blocking)

| # | Item | Proposed answer | Where documented | Confirmed? |
|---|------|-----------------|------------------|:----------:|
| A1 | **ADR-13** two-step checkout (`POST /api/orders`, then `POST /api/payments`) | Accepted | implementation_decisions.md, service_communication.md | [x] 2026-10-29 |
| A2 | **OPEN-01** the pre-Day-1 code scaffold (FastAPI stubs, Dockerfiles, PostgreSQL compose) | Rewrite on Day 2 to match the docs (MySQL, `/api` paths) | implementation_decisions.md | [ ] |
| A3 | **OPEN-12** ID format | UUID | implementation_decisions.md | [ ] |
| A4 | **OPEN-06** JWT signing | RS256 + JWKS endpoint | implementation_decisions.md | [ ] |
| A5 | **OPEN-02** MySQL layout | One server, five databases, runtime and migration user per service | database_ownership.md | [ ] |
| A6 | **OPEN-14** validation error format | 422 + ShopEase envelope, raw input removed | rest_api_notes.md §1.9 | [ ] |
| A7 | **Git**: initialize a repository and connect GitHub | Only when explicitly instructed | — | [ ] |

Non-blocking open questions (sensible defaults are documented): OPEN-04, -05, -07, -08,
-09, -10, -11 (scaffold part).

## B. Day 1 deliverables (verified present at handover)

- [x] `docs/README.md`: objective, scope, stack, timeline, deliverables, index
- [x] `docs/day1_progress.md`: progress report
- [x] `docs/implementation_decisions.md`: ADR-01 to ADR-13, OPEN-01 to OPEN-14
- [x] `docs/monolithic_vs_microservices.md`
- [x] `docs/service_responsibilities.md`
- [x] `docs/database_ownership.md` + `docs/database_ownership.mmd`
- [x] `docs/rest_api_notes.md`
- [x] `docs/service_communication.md` + `docs/checkout_sequence.mmd`
- [x] `docs/shopease_architecture.md` + `docs/shopease_architecture.mmd`
- [x] `docs/architecture.md` (one-page summary)

Validation performed at handover: all 6 Mermaid diagrams parse with Mermaid 11.4.1, and the
cross-document consistency checks pass. Results are in [day1_progress.md](day1_progress.md).

## C. Recommended Day 2 implementation order

Each step ends with something testable in Swagger UI (`http://localhost:<port>/docs`).

| Step | Build | Done when |
|------|-------|-----------|
| 1 | **Foundation:** resolve A1–A6; rewrite `docker-compose.yml` for MySQL with an init script creating `auth_db`…`payment_db` plus per-service users; update `.env.example` (placeholders only) | `docker compose up` starts MySQL with five databases; each service user can reach only its own |
| 2 | **Shared helpers** (thin): JWT verification via JWKS, error envelope, `X-Request-ID` middleware, structured JSON logging, custom 422 handler | Importable by every service; no models or sessions shared |
| 3 | **auth_service**: Alembic + `auth_users`, `refresh_tokens`, `service_clients`; register, login, refresh, logout, JWKS, service token | Register → login returns a JWT that verifies against the JWKS |
| 4 | **product_service**: catalog, categories, admin CRUD, `inventory`, reservations (reserve/confirm/release, idempotent per `order_id`, expiry) | Browse works; concurrent reservations never oversell |
| 5 | **api_gateway**: `/api/*` routing, edge JWT check, request IDs, `/internal/*` blocked, timeouts, rate limit | Register, login and browse work end to end through port 8000 |
| 6 | **user_service**: profile (created on first access), addresses, internal address lookup | `GET /api/users/me` and addresses work through the gateway |
| 7 | **order_service**: create order (price check, address snapshot, reservation), history, cancel, payable view, payment-result, expiry job, idempotency | Order reaches `AWAITING_PAYMENT`; out-of-stock gives `409` |
| 8 | **payment_service** with the **mock provider** (succeed / decline / timeout modes): payments, idempotency, one active payment per order, payment-result, reconciliation, refunds | Full checkout reaches `PAID`; decline, timeout (`202` then reconcile) and refund flows behave as in checkout_sequence.mmd |
| 9 | **Postman collection** and smoke tests for the happy path and the four alternative flows | Collection runs green against `docker compose up` |
| 10 | **Docs touch-up**: mark implemented contracts, record any deviations as new ADRs | Docs match the code |

Why this order: dependencies point downward (ADR-11), so the leaf services (auth,
product, user) come before the coordinating ones (order, then payment). The gateway arrives
as soon as there is something to route.

## D. Rules to keep while implementing

- [ ] No shared SQLAlchemy models or sessions; each service has its own Alembic history.
- [ ] No service connects to another service's database.
- [ ] Every outgoing call has a timeout; at most 1 inline retry; no unbounded loops.
- [ ] `Idempotency-Key` required on `POST /api/orders` and `POST /api/payments`.
- [ ] No raw card data, passwords, tokens or payment tokens in logs, DB or error bodies.
- [ ] Internal endpoints require a service token with a scope, even on the internal network.
- [ ] Commit or push only when explicitly instructed.
