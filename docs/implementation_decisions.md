# Implementation Decisions

This log records architecture decisions and the questions still open. Each decision has an ID,
so later documents and code can point to it.

Status values: **Accepted** · **Proposed** · **Open**

## Decisions

### ADR-01 — Microservices architecture
- **Status:** Accepted
- **Decision:** Split the system into five domain services: auth, user, product, order and
  payment. A single API gateway sits in front of them.
- **Reason:** Each domain has different load, change rate and isolation needs. Catalog
  reads are heavy, and payments need stricter isolation. See
  [monolithic_vs_microservices.md](monolithic_vs_microservices.md).
- **Trade-off:** More moving parts, network failures, and no cross-service transactions.

### ADR-02 — Database per service
- **Status:** Accepted
- **Decision:** Each service owns a private MySQL schema. There are no cross-service joins
  and no shared tables. Services refer to each other's records by ID only.
- **Reason:** Loose coupling and independent schema changes. See
  [database_ownership.md](database_ownership.md).

### ADR-03 — Technology stack
- **Status:** Accepted
- **Decision:** Python + FastAPI, MySQL, SQLAlchemy, Alembic, Pydantic, JWT, Docker Compose.
- **Reason:** This is the project's target stack. FastAPI produces Swagger UI automatically.

### ADR-04 — Synchronous REST between services
- **Status:** Accepted
- **Decision:** Services call each other over HTTP/REST, with timeouts. Calls to the next
  service's URL come from environment variables.
- **Reason:** It's the simplest approach that fits the two-day deadline. Async messaging is
  deferred (see OPEN-05).

### ADR-05 — JWT verified at the gateway and in services
- **Status:** Proposed
- **Decision:** auth_service issues JWTs. The gateway rejects requests with missing or
  invalid tokens. Downstream services also verify the token locally with auth_service's verification key (public key if RS256, see OPEN-06),
  so they don't call auth_service on every request.
- **Reason:** Avoids making auth_service a bottleneck on every call.

### ADR-06 — REST conventions
- **Status:** Accepted
- **Decision:** Plural resource nouns, standard HTTP methods and status codes, `snake_case`
  JSON, and a single error format `{"error": {"code", "message"}}`. See
  [rest_api_notes.md](rest_api_notes.md).

### ADR-07 — Price snapshot on orders
- **Status:** Accepted
- **Decision:** `order_items` stores the product name and unit price at the time of purchase.
- **Reason:** Later catalog changes must not change past orders.

### ADR-08 — Authenticated service-to-service calls
- **Status:** Proposed
- **Decision:** Internal calls carry a short-lived **service JWT** issued by auth_service
  through a client-credentials exchange (`sub=svc:<name>`, limited `scope`s such as
  `inventory:reserve`). When a service acts for a user, it also forwards the user's JWT.
  Internal endpoints live under `/internal/*`. The gateway never routes them, and the
  receiving service still checks the service token and its scope.
- **Reason:** The internal Docker network alone is not a security boundary. A compromised
  container or an SSRF bug could otherwise call internal endpoints.
- **Related:** OPEN-06 (signing algorithm). See
  [service_responsibilities.md](service_responsibilities.md#cross-cutting-rules).

### ADR-09 — User profiles created on first access
- **Status:** Proposed
- **Decision:** user_service creates an empty profile the first time a user calls
  `/api/users/me`, keyed by the JWT `sub`. auth_service does not call user_service during
  registration.
- **Reason:** It removes a runtime dependency from auth to user. Registration doesn't fail
  when user_service is down, and the dependency graph stays acyclic.
- **Trade-off:** A registered user has no profile row until their first profile request.
  Admin user lists must account for this.

### ADR-10 — Payments started only by order_service
- **Status:** Superseded by ADR-13
- **Decision:** Clients cannot create a payment directly. order_service starts the payment
  during checkout through `POST /internal/payments`. Clients can only **read** payments
  for their own orders.
- **Reason:** The charged amount always comes from the order, so the payment and the order
  can't diverge. Payment-start logic lives in one place.

### ADR-11 — Acyclic service dependencies
- **Status:** Accepted
- **Decision:** Service calls form a directed acyclic graph. auth_service, user_service and
  product_service call no other service. With the two-step checkout (ADR-13),
  payment_service calls order_service and the provider; order_service calls product_service
  and user_service and **never** calls payment_service. Services never call each other
  through the gateway. (This replaces the earlier wording, where order_service called
  payment_service under ADR-10.)
- **Reason:** Cyclic calls make deployment order, failure handling and reasoning about the
  system much harder. See the dependency check in
  [service_responsibilities.md](service_responsibilities.md#dependency-graph-and-circular-dependency-check).

### ADR-12 — `/api` prefix on public paths
- **Status:** Proposed
- **Decision:** All public routes start with `/api/<service>/...` (for example,
  `/api/auth/login`, `/api/orders/{order_id}`). The gateway forwards paths unchanged.
  `/internal/...` is never routed. Breaking changes would move to `/api/v2/...`.
- **Reason:** It clearly separates the API from other gateway paths (`/health`, a future
  static frontend), and each service's Swagger UI shows the same paths clients use.
- **Note:** [service_responsibilities.md](service_responsibilities.md) lists public paths
  without the prefix. [rest_api_notes.md](rest_api_notes.md) is the reference for exact paths.
  *(Resolved: since the architecture review, all docs use the `/api` prefix.)*

### ADR-13 — Two-step checkout
- **Status:** Accepted (confirmed by the project owner on 2026-10-29). It is the baseline in all Day 1 docs.
- **Decision:** `POST /api/orders` validates the order, reserves stock and creates it as
  `AWAITING_PAYMENT` with `payment_due_by`. The client then calls `POST /api/payments` with
  the `order_id` and a provider payment-method token. payment_service gets the payable amount
  from order_service (never from the client), charges through the provider abstraction (dev
  mock), and reports the result to order_service, which confirms stock and sets `PAID`. A
  declined payment leaves the order `AWAITING_PAYMENT` (retry allowed). Unpaid orders expire
  to `CANCELLED`, with stock released. A successful payment that order_service can't accept
  is refunded by payment_service.
- **Reason:** It matches the required public route `POST /api/payments`. A declined card
  doesn't lose the order. Order and payment retries are separately idempotent. `202` for
  uncertain payment outcomes fits naturally on the payment resource.
- **Trade-offs:** The client makes two calls. Abandoned orders need an expiry job. Refunds
  start on payment_service. payment_service depends on order_service (payment → order); the
  reverse call is removed, so the graph stays acyclic (ADR-11).
- **Supersedes:** ADR-10.
- **Documents:** [service_communication.md](service_communication.md),
  [checkout_sequence.mmd](checkout_sequence.mmd), [rest_api_notes.md](rest_api_notes.md) §3.6,
  [service_responsibilities.md](service_responsibilities.md) §4–5.

### ADR-14 — Thin shared package and pinned per-service dependencies
- **Status:** Proposed (applied in the Day 2 skeleton, 2026-10-30). Answers OPEN-10.
- **Decision:** Cross-cutting infrastructure lives in one small installable package,
  `shared/` (`shopease-shared`): JSON logging, the `X-Request-ID` middleware, the error
  envelope and its exception handlers, health routes and a base settings class. It contains
  no models, database sessions, business rules or service clients. Each component has its
  own `requirements.txt` with exact pins; the pins are identical across components so one
  local virtual environment (`requirements-dev.txt`) serves all of them. Docker images
  build from the repository root and install `shared/` next to the service's own pins.
- **Reason:** One error format and one log format across services without copy-paste, while
  business code and data access stay inside the owning service (ADR-02).
- **Trade-offs:** A change to `shared/` affects every image that is rebuilt afterwards, so it
  must stay small and backwards compatible. Pins are bumped together, in one change.

### ADR-15 — Per-service persistence conventions
- **Status:** Proposed (applied 2026-10-30).
- **Decision:** Each service has its own declarative `Base` and metadata, engine, session
  factory, models, schemas and Alembic history; none of it is shared or imported across
  services. Column conventions: UUID keys as `CHAR(32)`, UTC `DATETIME(6)`, `DECIMAL(12,2)`
  money, enums as `VARCHAR` plus named `CHECK` constraints, a constraint naming convention.
  Request handlers get one session per request; anything not committed is rolled back, and
  the session is always closed. Migrations run as the per-service migration user, never on
  service start, with revision IDs prefixed by the service name (`order_0001`).
- **Reason:** Database ownership (ADR-02) carried down to the code. Portable enums and
  constraints let the same models be tested on SQLite and enforced on MySQL 8. Prefixed
  revision IDs make a migration run against the wrong database fail loudly.
- **Trade-offs:** `CHAR(32)` UUIDs use more index space than `BINARY(16)` but are readable in
  SQL tools. Changing an enum needs a migration that replaces its `CHECK` constraint.
- **Documents:** [database_setup.md](database_setup.md),
  [database_ownership.md](database_ownership.md) (Day 2 implementation notes).

### ADR-16 — Authentication implementation
- **Status:** Accepted (confirmed by the project owner on 2026-10-30), including OPEN-06/07/08
  and keeping `409 EMAIL_ALREADY_REGISTERED` on registration.
- **Decision:** auth_service signs RS256 JWTs with a private key from the environment and
  publishes the public key as JWKS. The gateway and every service verify locally with a
  shared verifier (`shopease_shared.security`) that pins the algorithm and checks issuer,
  audience, expiry and a `token_use` claim separating user access tokens from service
  tokens. Passwords and client secrets use Argon2id. Refresh tokens are opaque, hashed,
  rotated with reuse detection. Internal calls use client-credentials service tokens with
  scopes plus the forwarded user token in `X-User-Token` (ADR-08). The gateway
  authenticates and rate-limits; services authenticate again and authorize.
- **Reason:** No shared secret leaves auth_service; Auth Service is off the request path
  (cached JWKS); the boundary holds even if the gateway is bypassed.
- **Trade-offs:** Access tokens can't be revoked early (15-minute window). In-memory rate
  limits are per gateway process. See [security_model.md](security_model.md) §9.

### ADR-17 — Inventory concurrency and reservations
- **Status:** Proposed (applied 2026-10-30). Implements OPEN-09.
- **Decision:** Stock changes run in one transaction that locks the affected `inventory`
  rows with `SELECT ... FOR UPDATE` in `product_id` order and checks availability under the
  lock. CHECK constraints and the optimistic `version` column are the second line of
  defense. Product Service's MySQL sessions use READ COMMITTED (no gap locks); deadlocks and
  lock timeouts are retried up to 3 times, then `503 SERVICE_BUSY`. Reservations stay keyed
  by `order_id` (`/internal/reservations/{order_id}/confirm|release`), not by a
  reservation ID: order_service always knows its order ID, even when a reserve call timed
  out and it must release without knowing whether anything was reserved. Every change writes
  an `inventory_movements` row with both deltas, the levels after, the actor and a note
  (migration `product_0002`).
- **Reason:** No overselling under concurrency, safe retries, and an audit trail that adds up.
- **Verified:** MySQL 8.0.46, five consecutive runs: 30 buyers for 10 units, crossed
  multi-item orders, admin removals racing reservations, duplicate same-order requests,
  confirm racing release. A negative control without `FOR UPDATE` lost 28 of 30 requests to
  the version check, showing the tests detect missing locking.
- **Trade-offs:** Hot products serialize on one row lock. The expiry job runs in each
  Product Service instance (SKIP LOCKED keeps several instances from colliding).

### ADR-18 — Order checkout coordination
- **Status:** Proposed (applied 2026-10-30). Builds on ADR-13 (accepted) and ADR-17.
- **Decision:** order_service validates prices (product_service) and the address
  (user_service) before storing anything, stores the order `PENDING`, reserves stock, then
  moves it to `AWAITING_PAYMENT`. It never calls payment_service: payments arrive through
  `GET /internal/orders/{id}/payable` and `POST /internal/orders/{id}/payment-result`
  (ADR-13). No database transaction is held across a network call; each local step locks the
  order row and re-checks its status. product_service's reservation decides races between
  paying and cancelling. Unknown reservation outcomes are compensated by an idempotent
  release; a recovery job expires unpaid orders, cleans up abandoned ones and retries
  failed releases. `Idempotency-Key` is unique per user in `order_db` (migration
  `order_0002` adds `payment_status`, `cancel_reason`, `release_pending`).
- **Reason:** No duplicate orders, no stranded stock, no double charges, and a status that
  only changes after the owning service has decided.
- **Trade-offs:** An expired order can still receive a successful payment, which is then
  refunded. The recovery job runs in every instance (idempotent). See
  [order_workflow.md](order_workflow.md) §6 for gaps.

### ADR-19 — Payment processing with a provider adapter and mock
- **Status:** Proposed (applied 2026-10-30). Completes ADR-13.
- **Decision:** payment_service talks to providers only through `PaymentProvider`
  (`charge`, `get_status`, `refund`). The only implementation is a **mock** for development
  and tests, refused when `APP_ENV=production`. A payment is recorded before charging,
  charged with its own ID as the provider idempotency key, and set `SUCCEEDED` only after an
  accepted result whose amount, currency and unique reference check out. Timeouts become
  `PROCESSING` and are reconciled on a bounded schedule, then flagged for manual review;
  charges are never repeated. Results are reported to order_service with background
  retries; payments order_service can't accept are refunded automatically. Status names
  stay as in `payment_0001` (`INITIATED` ≈ pending, `PROCESSING` ≈ requires reconciliation).
- **Reason:** No double charges, no false successes, no card data, and a clean seam for a
  real gateway.
- **Documents:** [payment_processing.md](payment_processing.md).

## Unresolved Questions

| ID | Question | Options | Notes |
|----|----------|---------|-------|
| OPEN-01 | Remove or rewrite the code scaffold that was generated before the Day 1 rules were given? | (a) Delete it before Day 2 (b) Keep it and rewrite it on Day 2 (c) Move it to a separate branch | The scaffold contains FastAPI stubs, Dockerfiles, a gateway proxy, `docker-compose.yml` with **PostgreSQL**, `.env.example` and `tests/test_health.py`. It breaks the Day 1 documentation-only rule and the MySQL target. It was preserved as instructed, and is not part of the Day 1 deliverables. **Deferred to Day 2 (2026-10-29): leave untouched for now.** **Resolved (2026-10-30): (b)**: the scaffold was read and rewritten into the Day 2 service skeletons (MySQL, `/api` paths, shared package). |
| OPEN-02 | One MySQL server with a separate schema per service, or one MySQL container per service? | (a) One server, five schemas, a separate DB user per service (b) Five containers | (a) is lighter for local work and still keeps ownership separate if each service gets its own DB user. **Proposed: (a) for development**, with databases `auth_db`, `user_db`, `product_db`, `order_db`, `payment_db`, plus a runtime user and a migration user per service. Separate instances are an option for production. See [database_ownership.md](database_ownership.md). |
| OPEN-03 | Build the API gateway ourselves in FastAPI, or use an off-the-shelf proxy (Nginx/Traefik)? | (a) FastAPI proxy (b) Nginx (c) Traefik | A FastAPI gateway can verify JWTs in Python. Nginx is simpler but needs extra setup for auth. |
| OPEN-04 | How do we keep order and payment consistent when payment succeeds but the stock update fails? | (a) Orchestrated saga in order_service (b) Choreography through events | Needs compensating actions: refund and release stock. **Proposed:** orchestration split by ownership under ADR-13. order_service coordinates order and stock steps; payment_service coordinates payment steps and reports results. Compensation: release stock, refund. |
| OPEN-05 | Add a message broker (RabbitMQ / Redis Streams) now or later? | (a) Day 2 (b) After the deadline | Probably out of scope for two days. |
| OPEN-06 | JWT signing: shared secret (HS256) or key pair (RS256)? | HS256 / RS256 | With RS256, other services only need the public key, which is safer. HS256 is simpler. **Proposed: RS256**, with a JWKS endpoint on auth_service. This also covers the service tokens in ADR-08. **Resolved (accepted by the project owner, 2026-10-30): RS256 + JWKS** (ADR-16). |
| OPEN-07 | Token lifetime and refresh-token strategy | Access-token lifetime; whether refresh tokens are stored and revoked | **Resolved (accepted by the project owner, 2026-10-30):** access 15 min, service 5 min, refresh 14 days, stored as SHA-256, rotated on every use with reuse detection, revoked on logout and password change (ADR-16). |
| OPEN-08 | Are roles (customer/admin) needed, and where are they enforced? | Role claim in the JWT plus checks in each service | Needed for `POST /api/products` (admin). **Proposed:** roles `customer` and `admin` in the JWT `role` claim. Each service enforces roles plus ownership; the gateway does not. **Resolved (accepted by the project owner, 2026-10-30):** `role` claim, enforced in each service; first admin via `scripts/auth_cli.py promote-admin`. |
| OPEN-09 | Stock reservation: subtract stock when the order is created or when payment succeeds? | On create (with expiry) / on payment | Affects overselling risk. **Proposed:** reserve at order creation, with an expiry; confirm on payment success; release on failure or expiry. **Implemented as proposed (2026-10-30)**, ADR-17. |
| OPEN-10 | Where does shared code live (JWT helper, error schema)? | A `shared/` package copied into each image / a small internal pip package / duplicated per service | A shared package couples services' releases together. **Resolved (2026-10-30): ADR-14**, a thin installable `shared/` package with infrastructure only. |
| OPEN-11 | Update existing docs that say PostgreSQL to say MySQL? | Edit now / Edit on Day 2 | `docs/architecture.md` and the scaffold files mention PostgreSQL. **Docs: resolved** during the architecture review (2026-10-29); `docs/architecture.md` now says MySQL. **Scaffold files** (`docker-compose.yml`, `.env.example`): still PostgreSQL, deferred to Day 2. **Resolved (2026-10-30):** both now target MySQL. |
| OPEN-12 | Primary-key and external-ID format across services | (a) UUID (stored as `BINARY(16)` or `CHAR(36)`) (b) `BIGINT AUTO_INCREMENT` | **Proposed: (a)**. IDs can be generated independently by each service, and they don't reveal record counts in URLs. Trade-off: larger indexes. Must be the same format everywhere, since IDs are stored across services without foreign keys. |
| OPEN-13 | Who starts payments? | (a) **ADR-10:** order_service starts payment inside `POST /api/orders`; no client `POST /api/payments` (b) **Two-step checkout:** `POST /api/orders` creates an `AWAITING_PAYMENT` order, then the client calls `POST /api/payments` | **Resolved (2026-10-29): (b), accepted as ADR-13** and applied across all Day 1 docs. Choosing (a) instead would mean restoring ADR-10 and updating rest_api_notes §3.6, service_responsibilities §4–5, service_communication steps 7–8, checkout_sequence.mmd and database_ownership §7. |
| OPEN-14 | Validation error format | (a) FastAPI default 422 `{"detail": [...]}` (b) Custom `RequestValidationError` handler: still 422, but the ShopEase error envelope, with raw input values removed | **Proposed: (b)**. One error format for clients, and passwords are not repeated back in error bodies. |
