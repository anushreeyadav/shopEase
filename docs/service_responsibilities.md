# Service Responsibilities and Boundaries

This document defines what each ShopEase component owns, who it talks to, and what it must
never do. It is the reference for deciding *where* a piece of logic or data belongs.

Related: [shopease_architecture.md](shopease_architecture.md) ·
[database_ownership.md](database_ownership.md) · [rest_api_notes.md](rest_api_notes.md) ·
[service_communication.md](service_communication.md) ·
[implementation_decisions.md](implementation_decisions.md)

> **Paths** use the public `/api` prefix (ADR-12). Full request/response contracts are in
> [rest_api_notes.md](rest_api_notes.md).
> **Checkout model:** two-step checkout (ADR-13, accepted): the client
> creates an order, then pays for it with `POST /api/payments`.

---

## Cross-Cutting Rules

These rules apply to every service.

### Boundaries
1. **The gateway contains no business logic.** It routes, authenticates at the edge, limits
   rates and tags requests. Rules about prices, stock, order states or payments live only in
   the service that owns them.
2. **No shared SQLAlchemy models or database sessions.** Each service defines its own models,
   its own engine/session and its own Alembic migrations. Shared code is limited to
   framework-level helpers, such as JWT verification and the error schema (see OPEN-10).
3. **No direct access to another service's tables.** Each service connects with its own
   MySQL user, which only has privileges on its own database. For example, order_service
   **cannot** update `product_db.inventory`. It must call product_service's API.
4. **Reference by ID, snapshot what must not change.** Services store foreign IDs (for
   example, `user_id`) without database foreign keys across databases. They copy data that
   must stay fixed in history, such as the price at purchase time or the delivery address.

### Authentication vs. authorization
| Concept | Question it answers | Where it happens in ShopEase |
|---------|--------------------|------------------------------|
| **Authentication** | *Who is calling?* Is the JWT genuine, unexpired and issued by auth_service? | auth_service issues tokens. The gateway **and** each service verify the signature and expiry. |
| **Authorization** | *Is this caller allowed to do this action on this resource?* | Inside **each owning service**, using claims from the verified token (`sub`, `role`, `scope`) **plus** ownership checks (for example, "is this order yours?"). |

A valid JWT proves identity only. It does **not** grant permission. Every service checks its
own authorization rules even after the gateway has authenticated the request.

**Roles (proposed, see OPEN-08):** `customer`, `admin`. **Service identities:** `svc:order`,
`svc:payment`, and so on, used for internal calls.

### Internal (service-to-service) requests must be authenticated
Being on the internal Docker network **is not** proof of trust. Any compromised container,
misconfigured port or SSRF bug could reach internal endpoints. Therefore:

- Every internal call carries a **service credential**: a short-lived service JWT that
  auth_service issues to each service through a client-credentials exchange. It carries
  `sub=svc:<name>` and limited `scope`s (for example, `inventory:reserve`).
- When acting for an end user, the caller also **forwards the user's JWT**, so the
  receiving service knows both *which service* is calling and *on whose behalf*.
- Internal-only endpoints live under `/internal/...`. The gateway **never routes**
  `/internal/*` from clients. Even so, the receiving service still requires and checks the
  service token and its scope. Not being routed is defense in depth, not the control
  itself.
- Mutual TLS is a possible later hardening step. It is not required for Day 2.

### Request correlation
The gateway assigns an `X-Request-ID` to each request, or accepts a valid one from the
client. Every service logs it and passes it on in outgoing calls.

### Standard error body
```json
{"error": {"code": "OUT_OF_STOCK", "message": "Only 2 units of 'Trail Running Shoe' are available.", "request_id": "req-7d52"}}
```

---

## 1. Authentication Service (`auth_service`)

### Purpose and responsibilities
Owns **credentials and tokens**. It is the only component that knows passwords or issues
tokens.
- **Registration:** create a credential record (email + password hash). Enforce a password
  policy and unique emails.
- **Login:** check credentials and issue an access token (short-lived JWT) and a refresh
  token.
- **Password hashing:** a slow, salted algorithm (bcrypt or argon2). Plain-text or
  reversible passwords are never stored or logged.
- **JWT issuance:** sign tokens containing `sub` (user id), `role`, `iat`, `exp`, `iss`,
  `aud` and `jti`.
- **Token validation strategy:** other services validate tokens **locally** using the
  signing key, so they don't call auth_service on each request. RS256 is recommended, so
  services only hold the public key (published via a JWKS endpoint); see OPEN-06.
- **Refresh and logout:** rotate refresh tokens. Revoke on logout or password change.
- **Policies:** login rate limiting and lockout after repeated failures, password strength,
  token lifetimes (OPEN-07), and the same generic error for "unknown email" and "wrong
  password", so attackers can't discover which emails are registered.
- **Service credentials:** issue service JWTs to registered internal services.

### Data it owns (`auth_db`)
`auth_users` (id, email, password_hash, role, status, failed_login_attempts, locked_until),
`refresh_tokens` (token hash, user_id, expires_at, revoked_at), `service_clients`
(client_id, secret hash, allowed scopes).

### Example endpoints
| Method | Path | Access |
|--------|------|--------|
| POST | `/api/auth/register` | Public |
| POST | `/api/auth/login` | Public |
| POST | `/api/auth/refresh` | Public (valid refresh token required) |
| POST | `/api/auth/logout` | Authenticated user |
| PUT | `/api/auth/password` | Authenticated user |
| GET | `/api/auth/.well-known/jwks.json` | Public (public keys only) |
| PATCH | `/api/auth/users/{user_id}/role` | Admin |
| POST | `/internal/auth/service-token` | Internal service (client credentials) |

### Calls
None. auth_service has **no outgoing dependencies**, which keeps it simple and avoids cycles.

### Called by
API gateway (client traffic, fetching the JWKS); all other services (service-token requests
and the JWKS, usually cached).

### Must not own or access
User profile data (names, phones, addresses), orders, payments. It must never return
password hashes in any response.

### Main failure cases
Duplicate email; wrong credentials; account locked; expired or revoked refresh token; weak
password; signing key unavailable or misconfigured (then no tokens can be issued, so this
is critical); brute-force attempts.

### Authorization
Register, login, refresh and JWKS are public. Logout and password change need the user's own
valid token. Changing roles is admin-only. The service-token endpoint needs valid client
credentials.

### Expected status codes
`200` login/refresh OK · `201` registered · `204` logout/password changed · `400` malformed ·
`401` wrong credentials or invalid token · `403` not an admin · `409` email already
registered · `422` validation (weak password, bad email) · `423` account locked (or `429`) ·
`429` too many attempts · `500`

---

## 2. User Service (`user_service`)

### Purpose and responsibilities
Owns **who the customer is**, apart from their credentials.
- User profile: display name, contact email for notifications, phone number.
- Delivery addresses: add, replace, delete, set a default.
- **Lazy profile creation (ADR-09):** the first authenticated call to `/api/users/me` creates
  an empty profile keyed by the JWT `sub`. This avoids a synchronous auth → user call during
  registration, so neither service depends on the other at runtime.

### Data it owns (`user_db`)
`user_profiles` (user_id = JWT `sub`, full_name, phone, contact_email, timestamps),
`user_addresses` (id, user_id, label, line1, line2, city, state, postal_code, country, is_default).

### Example endpoints
| Method | Path | Access |
|--------|------|--------|
| GET | `/api/users/me` | Authenticated user |
| PATCH | `/api/users/me` | Authenticated user |
| GET | `/api/users/me/addresses` | Authenticated user |
| POST | `/api/users/me/addresses` | Authenticated user |
| PUT | `/api/users/me/addresses/{address_id}` | Owner of the address |
| DELETE | `/api/users/me/addresses/{address_id}` | Owner of the address |
| GET | `/api/users/{user_id}` | Admin |
| GET | `/internal/users/{user_id}/addresses/{address_id}` | Service token, scope `addresses:read` (order_service) |

### Calls
None at runtime (it validates tokens locally with the cached JWKS).

### Called by
API gateway; order_service (to fetch a delivery address at checkout).

### Must not own or access
Passwords, password hashes, tokens or roles (owned by auth_service), orders, payments.

### Main failure cases
Profile not found (for admin lookup); address belonging to another user; invalid address
fields; deleting the only default address; order_service asking for an address that
doesn't belong to the user on the forwarded JWT.

### Authorization
Users can read and change only their **own** profile and addresses (`sub` must match the
resource owner). Admins can read any profile. The internal address lookup needs a service
token with `addresses:read` **and** checks that the address belongs to the user on the
forwarded JWT.

### Expected status codes
`200` · `201` address created · `204` deleted · `400` · `401` · `403` not an admin · `404`
profile or address not found (including another user's address) · `409` the default address
can't be deleted · `422` validation · `500`

---

## 3. Product Service (`product_service`)

### Purpose and responsibilities
Owns **what is for sale, at what price, and how many are available**.
- Product catalog: create, update, archive products; search, filter, paginate.
- Categories.
- **Pricing:** the current price for each product. It is the single source of truth.
- **Stock availability:** on-hand and reserved quantities.
- **Inventory changes:** reserve, confirm (deduct) and release stock atomically, with
  checks against negative stock. All stock changes go through this service.
- Idempotent reservation operations, keyed by `order_id`, so retries don't double-reserve.
- Releases its own expired reservations (it never needs to call order_service).

### Data it owns (`product_db`)
`categories`, `products` (id, sku, name, description, category_id, price, currency, status),
`inventory` (product_id, quantity_on_hand, quantity_reserved),
`stock_reservations` (order_id, product_id, quantity, status, expires_at),
`inventory_movements` (append-only audit record of stock changes).

### Example endpoints
| Method | Path | Access |
|--------|------|--------|
| GET | `/api/products` | Public |
| GET | `/api/products/{product_id}` | Public |
| GET | `/api/categories` | Public |
| POST | `/api/products` | Admin |
| PATCH | `/api/products/{product_id}` | Admin |
| DELETE | `/api/products/{product_id}` (archive) | Admin |
| PATCH | `/api/products/{product_id}/inventory` | Admin (manual stock adjustment) |
| POST | `/internal/products/price-check` | Service token, scope `products:read` |
| POST | `/internal/reservations` | Service token, scope `inventory:reserve` |
| POST | `/internal/reservations/{order_id}/confirm` | Service token, scope `inventory:reserve` |
| POST | `/internal/reservations/{order_id}/release` | Service token, scope `inventory:reserve` |

### Calls
None. product_service is a **leaf service**.

### Called by
API gateway; order_service (price checks, reservations).

### Must not own or access
Orders, users, payments. It doesn't know *why* stock is reserved beyond the `order_id`
reference.

### Main failure cases
Product not found or archived; not enough stock; concurrent reservations racing for the
last units (handled with row-level locking or a conditional update); duplicate SKU;
confirming a reservation that has expired (`409 RESERVATION_EXPIRED`); price changing
between the customer viewing it and placing the order.

### Authorization
Catalog reads are public. Catalog and inventory changes are admin-only (role check).
Reservation endpoints need a service token with `inventory:reserve`. Customers can never
change stock directly.

### Expected status codes
`200` · `201` product/reservation created · `204` archived · `400` · `401` · `403` not an
admin / missing scope · `404` product or reservation not found · `409` not enough stock /
duplicate SKU / reservation expired or already in a final state · `422` · `500`

---

## 4. Order Service (`order_service`)

### Purpose and responsibilities
Owns **orders, their status, and the order and inventory part of checkout**.
- **Order creation:** validate the cart, get current prices from product_service, fetch and
  copy the delivery address from user_service, create the order as `PENDING`, reserve stock,
  then move it to `AWAITING_PAYMENT` with a `payment_due_by` time.
- **Order items:** a price and name snapshot for each line item.
- **Order history:** list and view a customer's orders.
- **Status changes:** enforce valid transitions (below). Reject invalid ones.
- **Payable view for payment_service:** expose the authoritative amount, owner and status
  of an order, so the amount is never taken from the client.
- **Applying payment results:** when payment_service reports a result, confirm the stock
  reservation and set `PAID`, or keep `AWAITING_PAYMENT` after a decline. If stock can no
  longer be confirmed, cancel the order and answer `409`, so payment_service refunds.
- **Background jobs:** expire unpaid orders (`AWAITING_PAYMENT` past `payment_due_by` plus a
  grace period → `CANCELLED`, release stock), and clean up orders stuck in `PENDING`.
- Idempotency: `POST /api/orders` requires an `Idempotency-Key` header, so a client retry
  doesn't create two orders.

**Status transitions** (full table in
[service_communication.md](service_communication.md#order-states-proposed-for-the-two-step-checkout))
```
PENDING ──reserve ok──► AWAITING_PAYMENT ──payment ok + stock confirmed──► PAID ──► SHIPPED ──► DELIVERED
   │                         │   (payment declined: stays, retry allowed)    │
   │ out of stock /          │ expired / customer cancel /                    │ refund completed
   │ dependency failure      │ stock confirm failed after payment             │ (admin cancel)
   ▼                         ▼                                                ▼
CANCELLED ◄──────────────────┴────────────────────────────────────────────────┘
```

### Data it owns (`order_db`)
`orders` (id, user_id, status, total_amount, currency, shipping_address_snapshot,
idempotency_key, payment_id, payment_due_by, timestamps), `order_items` (order_id,
product_id, product_name_snapshot, unit_price_snapshot, quantity), `order_status_history`
(order_id, from_status, to_status, changed_by, reason, changed_at).

### Example endpoints
| Method | Path | Access |
|--------|------|--------|
| POST | `/api/orders` | Customer (+ `Idempotency-Key`) |
| GET | `/api/orders` | Customer (own orders) / Admin (all, filtered) |
| GET | `/api/orders/{order_id}` | Owner or Admin |
| POST | `/api/orders/{order_id}/cancel` | Owner (only before PAID) or Admin |
| PATCH | `/api/orders/{order_id}/status` | Admin (fulfilment: SHIPPED, DELIVERED) |
| GET | `/internal/orders/{order_id}/payable` | Service token, scope `orders:read` (payment_service) |
| POST | `/internal/orders/{order_id}/payment-result` | Service token, scope `orders:payment` (payment_service) |

### Calls
- product_service: price check, reserve, confirm, release stock.
- user_service: fetch the delivery address.
- auth_service: get a service token (cached until it expires).

It does **not** call payment_service.

### Called by
API gateway; payment_service (payable view, payment results).

### Must not own or access
Product tables or stock (it must use product_service's API, never write to
`product_db.inventory`); payment records, payment credentials or provider details; user
profiles beyond the copied address snapshot.

### Main failure cases
Empty cart or invalid quantity; product unavailable or not enough stock; product_service or
user_service timing out or unreachable (cancel, release, answer `503`); duplicate submission;
invalid status transition; a customer viewing someone else's order; a reservation expiring
before payment finishes; a payment result arriving for an order that has already been
cancelled (answer `409`, so payment_service refunds).

### Authorization
Customers can create orders and view or cancel only **their own** orders (ownership check on
`user_id = sub`). Fulfilment status changes are admin-only. Customers can never set `PAID`.
Only a payment result from payment_service (service token with `orders:payment`) can.

### Expected status codes
`200` · `201` order created · `400` · `401` · `403` not an admin / missing scope · `404` order
not found (including another user's order) · `409` not enough stock / invalid status
transition / idempotency-key conflict / order not fulfillable · `422` validation · `502` a
downstream service returned an invalid response · `503` a downstream service is unavailable
· `504` a downstream call timed out · `500`

---

## 5. Payment Service (`payment_service`)

### Purpose and responsibilities
Owns **money movement records** and is the **only** component that talks to a payment
provider.
- **Payment attempts:** the client pays for an `AWAITING_PAYMENT` order with
  `POST /api/payments`. The amount comes from order_service's payable view, **never from the
  client**. Several attempts per order are allowed over time (for example after a decline),
  but only **one active payment** at a time. Each attempt is idempotent per `Idempotency-Key`.
- **Transaction references:** store the provider's transaction ID and our internal payment ID.
- **Payment status:** `INITIATED → SUCCEEDED | FAILED | PROCESSING`, `PROCESSING → SUCCEEDED |
  FAILED` (after reconciliation), and `SUCCEEDED → REFUNDED`.
- **Reporting results:** tell order_service the outcome (`payment-result`). If that call
  fails, retry on a bounded background schedule.
- **Reconciliation:** resolve `PROCESSING` (unknown outcome) payments by asking the provider
  for the status. **Never charge again** automatically.
- **Refunds:** admin refunds, and automatic refunds when order_service rejects a successful
  payment (order expired or stock unavailable).
- **Provider integration boundary:** a provider adapter interface (`charge`, `refund`,
  `get_status`). ShopEase uses a **development mock** (out of scope: real providers). With
  a real provider, card data is collected and **tokenized by the provider on the client
  side**. ShopEase only ever receives an opaque payment-method token.
- **Provider webhooks** (if a real provider is used): check the provider's signature before
  trusting any status update.

### Sensitive data rules
- **Never store, log or send** raw card numbers (PAN), CVV/CVC, expiry dates combined with
  PAN, PINs or provider secret keys in any request log, database or error message.
- Store only: the provider token or reference, the card brand, and the last 4 digits (if the
  provider returns them).
- Provider API keys come from secret configuration, never from code or Git.

### Data it owns (`payment_db`)
`payments` (id, order_id, user_id, amount, currency, status, provider, provider_txn_ref,
idempotency_key, active_order_id, failure_reason, timestamps), `refunds` (id, payment_id,
amount, status, provider_refund_ref, reason), `payment_status_history` (audit record of
status changes and verified provider events).

### Example endpoints
| Method | Path | Access |
|--------|------|--------|
| POST | `/api/payments` | Owner of the order (+ `Idempotency-Key`) |
| GET | `/api/payments/{payment_id}` | Owner or Admin |
| GET | `/api/payments?order_id=` | Owner or Admin |
| POST | `/api/payments/{payment_id}/refunds` | Admin |
| POST | `/api/payments/webhooks/{provider}` | Provider (signature verified, no JWT) |

### Calls
- order_service: payable view, payment results.
- The payment provider (development mock).
- auth_service: get a service token (cached).

### Called by
API gateway only (customer payments and reads, admin refunds, provider webhooks).

### Must not own or access
Order status (it reports results; order_service decides the order state); stock; user
profiles; any raw card data.

### Main failure cases
Payment declined; provider timeout with an **unknown outcome** (record as `PROCESSING`,
answer `202`, reconcile, never charge twice); duplicate charge request (rejected by the
idempotency key and the one-active-payment rule); order not payable (already paid, expired,
cancelled); order_service unavailable (no charge is attempted); refund larger than the
captured amount; a webhook with an invalid signature; provider unavailable (circuit breaker
open → `503`, no charge).

### Authorization
Customers can pay for and read payments only for **their own** orders (the owner returned by
the payable view must match the JWT `sub`). Refunds are admin-only. Webhooks are
authenticated by the provider's signature, not a JWT.

### Expected status codes
`200` · `201` payment succeeded · `202` outcome pending (`PROCESSING`) · `400` · `401` · `403`
not an admin · `404` order or payment not found (including another user's) · `409` order not
payable / payment already in progress / idempotency conflict / order not fulfillable
(payment refunded) · `422` validation or `PAYMENT_DECLINED` · `502` invalid provider response
· `503` provider or order_service unavailable · `504` provider timeout · `500`

---

## 6. API Gateway (`api_gateway`)

### Purpose and responsibilities
The **single entry point** for all client traffic.
- **Routing:** `/api/auth/*`, `/api/users/*`, `/api/products/*` and `/api/categories`,
  `/api/orders/*`, `/api/payments/*` go to the owning service. `/internal/*` is **never**
  routed from outside.
- **Request correlation:** create or forward `X-Request-ID`. Log method, path, status and
  latency.
- **Rate limiting:** per IP and per user. Stricter limits on `/api/auth/login` and
  `/api/auth/register`.
- **Authentication enforcement at the edge:** for routes marked as protected, reject requests
  with a missing, malformed, expired or wrongly signed JWT (`401`) before they reach a
  service. Public routes (catalog reads, login, register, JWKS, provider webhooks) pass
  through without a token. The original `Authorization` header is forwarded unchanged.
- CORS, request size limits, TLS termination (in production), and a health endpoint.

### Data it owns
No business data. Only configuration (the route table, rate-limit rules, the cached JWKS)
and short-lived rate-limit counters.

### Example endpoints
`GET /health` and the proxied routes above.

### Calls
All five services (forwarding); auth_service's JWKS (cached).

### Called by
Clients (web/mobile apps, Postman), and payment providers for webhooks.

### Must not own or access
- Any database.
- **Business logic or detailed authorization**: it doesn't decide whether an order can be
  cancelled, whether a user owns a resource, or whether a user is an admin for a given
  action. Those checks live in the owning service. The gateway's JWT check is a coarse
  "is this caller authenticated?" filter.
- Response composition that includes domain rules.

### Main failure cases
Upstream service down (`503`) or slow (`504`); invalid or expired token (`401`); rate limit
exceeded (`429`); unknown route (`404`); request too large (`413`); JWKS unavailable (use the
cached keys; reject protected routes if there are none); the gateway itself being a single
point of failure (run several copies in production).

### Authorization
Authentication only, on protected routes. No role or ownership decisions.

### Expected status codes
Passes through upstream codes unchanged. It produces its own `401` · `404` unknown route ·
`413` · `429` · `502` invalid upstream response · `503` upstream unavailable · `504`
upstream timeout.

---

## Dependency Graph and Circular-Dependency Check

```
Layer 0   clients, payment-provider webhooks
              │
              ▼
Layer 1   api_gateway ──────────────► (forwards to every service below)
              │
              ▼
Layer 2   payment_service ──► payment provider (mock)
              │
              ▼
Layer 3   order_service
              │
              ├──► product_service
              └──► user_service

Leaf      auth_service · user_service · product_service    (call nobody)
          (every service may fetch the JWKS and service tokens from auth_service)
```

Arrows only point down a layer or to a leaf. No service calls one in a higher layer.

Call edges (caller → callee):

| Caller | Callees |
|--------|---------|
| api_gateway | auth, user, product, order, payment |
| payment_service | order, payment provider, auth (service token) |
| order_service | product, user, auth (service token) |
| auth_service | — |
| user_service | — |
| product_service | — |

**Result: no cycles.** The graph is a directed acyclic graph. Four design choices keep it that way:

1. **auth ↛ user:** profiles are created lazily by user_service from the JWT `sub`, instead
   of auth_service calling user_service during registration.
2. **order ↛ payment:** order_service never calls payment_service. Payment results are
   *pushed* to order_service. When order_service can't accept a successful payment, it answers
   `409` and payment_service refunds on its own.
3. **product ↛ order:** reservations carry the `order_id` as plain data, and product_service
   never calls order_service. Expired reservations are released by product_service itself.
4. **Nobody calls the gateway:** internal calls go directly to the target service with a
   service token.

---

## Service Ownership Matrix

**O** = owns (only writer) · **R** = reads through the owner's API · **S** = keeps a snapshot copy · **—** = no access

| Data / capability | auth | user | product | order | payment | gateway |
|-------------------|:----:|:----:|:-------:|:-----:|:-------:|:-------:|
| Credentials, password hashes | **O** | — | — | — | — | — |
| JWT issuing, refresh tokens, roles | **O** | — | — | — | — | verifies JWT |
| User profiles, contact details | — | **O** | — | — | — | — |
| Delivery addresses | — | **O** | — | R, S | — | — |
| Products, categories | — | — | **O** | R, S (name) | — | — |
| Prices | — | — | **O** | R, S (unit price) | — | — |
| Inventory, stock reservations | — | — | **O** | R (via API calls) | — | — |
| Orders, order items, status | — | — | — | **O** | R (payable view) | — |
| Order and inventory coordination at checkout | — | — | — | **O** | — | — |
| Payments, refunds, provider refs | — | — | — | S (`payment_id` only) | **O** | — |
| Payment flow and reconciliation | — | — | — | — | **O** | — |
| Provider integration | — | — | — | — | **O** | routes webhooks |
| Routing, rate limiting, request IDs | — | — | — | — | — | **O** |
| Authorization decisions (role, ownership) | own endpoints | own endpoints | own endpoints | own endpoints | own endpoints | — |

Each service has its own MySQL database and DB user (logical ownership on one shared MySQL
server, as proposed in OPEN-02). No two services have write access to the same database.
Full table lists: [database_ownership.md](database_ownership.md).

---

## Proposed Development Ports

These are **local development defaults** for Docker Compose and Swagger UI. They are not
production requirements. In production, services usually listen on a single internal port
behind the orchestrator's service discovery, and only the gateway is exposed publicly.

| Component | Port | Swagger UI (dev) |
|-----------|------|------------------|
| api_gateway | 8000 | — |
| auth_service | 8001 | http://localhost:8001/docs |
| user_service | 8002 | http://localhost:8002/docs |
| product_service | 8003 | http://localhost:8003/docs |
| order_service | 8004 | http://localhost:8004/docs |
| payment_service | 8005 | http://localhost:8005/docs |
| MySQL | 3306 | — |

Ports should be set through environment variables, not hard-coded. In shared or production
environments, the service ports and MySQL should **not** be published to the host. Only the
gateway should be reachable from outside.
