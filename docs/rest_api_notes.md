# REST API Design and HTTP Reference

> **Status: proposed API contracts, pending review.** Nothing here is implemented. Paths,
> fields and status codes will be reviewed before coding on Day 2.

All sample data is fictional. Passwords, tokens and payment tokens are **placeholders**, and
no real credentials or card data appear anywhere in this document.

Related: [service_responsibilities.md](service_responsibilities.md) ·
[database_ownership.md](database_ownership.md) ·
[implementation_decisions.md](implementation_decisions.md)

---

## Part 1 — HTTP and REST Fundamentals

### 1.1 Anatomy of a request

```
POST /api/orders?dry_run=false HTTP/1.1          <- method, path, query string
Host: localhost:8000
Authorization: Bearer <access_token>               <- authentication header
Content-Type: application/json                     <- format of the body
Accept: application/json                           <- format the client wants back
Idempotency-Key: 6f1c2d3e-4a5b-4c6d-8e7f-9a0b1c2d3e4f
X-Request-ID: req-7f3a9c2e                          <- optional; the gateway adds one if missing

{ "items": [ { "product_id": "9b8a...", "quantity": 1 } ] }   <- request body (JSON)
```

| Part | What it is | ShopEase convention |
|------|-----------|---------------------|
| **URL path** | Identifies a resource or collection | Plural nouns, lowercase, hyphens if needed: `/api/products`, `/api/orders/{order_id}` |
| **Path parameter** | Identifies *one specific* resource inside the path | `{product_id}`, `{order_id}`: UUIDs (OPEN-12). An invalid format → `422`; a valid ID that doesn't exist → `404` |
| **Query parameter** | Filters, sorts or pages a collection; never identifies the main resource | `GET /api/products?category_id=...&min_price=1000&sort=-price&limit=20&offset=0` |
| **Headers** | Metadata about the request: auth, formats, tracing, idempotency | See 1.3 |
| **Request body** | The data for `POST`, `PUT` or `PATCH`, as JSON | `snake_case` field names; unknown fields are rejected (`422`) |

### 1.2 JSON requests and responses

- `Content-Type: application/json` on every request that has a body. Responses are always JSON,
  except `204`, which has no body.
- Field names are `snake_case`. Timestamps are ISO 8601 in UTC: `"2026-10-29T10:15:30Z"`.
- **Money is a decimal string plus a currency**: `"price": "2499.00", "currency": "INR"`. This
  avoids floating-point rounding errors.
- IDs are UUID strings. Enumerations are UPPER_CASE strings: `"status": "AWAITING_PAYMENT"`.
- A single resource is returned as an object. A collection is wrapped in a pagination envelope
  (1.6), never returned as a bare array.
- `null` is used for "known to be empty". Fields are not silently left out.

### 1.3 Headers

| Header | Direction | Purpose |
|--------|-----------|---------|
| `Authorization: Bearer <access_token>` | Request | The JWT access token for protected routes |
| `Content-Type: application/json` | Both | The format of the body |
| `Accept: application/json` | Request | The format the client wants back |
| `Idempotency-Key: <uuid>` | Request | **Required** on `POST /api/orders` and `POST /api/payments`, so a retry doesn't create a duplicate |
| `X-Request-ID` | Both | Correlation ID. The gateway creates one if it's missing; every log line and error includes it |
| `Location` | Response | URL of a resource created with `201` (or of the status resource with `202`) |
| `Retry-After` | Response | Seconds to wait, sent with `429` and `503` |
| `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset` | Response | Current rate-limit status (from the gateway) |

### 1.4 Authentication headers

- After login, the client sends `Authorization: Bearer <access_token>` on every protected request.
- **Authentication** (is the token valid?) happens at the gateway and again in each service.
  **Authorization** (is this caller allowed to do this?) happens only in the owning service,
  using the token's `role` and ownership checks (see
  [service_responsibilities.md](service_responsibilities.md#authentication-vs-authorization)).
- Missing, malformed or expired token → `401` with `WWW-Authenticate: Bearer`.
  Valid token but not allowed → `403`.
- Tokens never go in query strings, because URLs end up in logs and browser history.
- Access levels used in this document:

| Label | Meaning |
|-------|---------|
| **Public** | No token needed |
| **Customer** | Valid token with `role = customer` (or admin) |
| **Owner** | Customer, **and** the resource belongs to the token's `sub` |
| **Admin** | Valid token with `role = admin` |
| **Service** | Internal service token with the listed scope; not reachable through the gateway |

### 1.5 HTTP methods

| Method | Meaning | Safe? | Idempotent? | Typical success | ShopEase example |
|--------|---------|:-----:|:-----------:|-----------------|------------------|
| **GET** | Retrieve a resource or collection | Yes | Yes | `200` | `GET /api/products/{product_id}` |
| **POST** | Create a resource, or start an action that isn't a simple update | No | **No** (made safe for retries with `Idempotency-Key`) | `201`, `202`, or `200` for actions | `POST /api/orders`, `POST /api/auth/login` |
| **PUT** | **Replace** the whole representation of a resource; missing fields are reset | No | Yes | `200` (or `204`) | `PUT /api/users/me/addresses/{address_id}` |
| **PATCH** | **Partially** update; only the fields sent are changed | No | Not guaranteed (it is for ShopEase's field-set patches) | `200` | `PATCH /api/users/me` |
| **DELETE** | Delete a resource, **if permitted** (many records are archived or cancelled instead) | No | Yes (a repeated delete gives `404`, or `204`, with no further effect) | `204` | `DELETE /api/users/me/addresses/{address_id}` |

- **Safe** means no change on the server. **Idempotent** means sending the same request N
  times leaves the server in the same state as sending it once.
- **Not everything can be deleted.** Orders and payments are financial records: they are
  *cancelled* or *refunded* with state-changing `POST` actions (for example,
  `POST /api/orders/{order_id}/cancel`), never `DELETE`d. Products are archived.

### 1.6 Pagination, filtering and sorting

Collections use **limit/offset** pagination:

```
GET /api/products?limit=20&offset=40&sort=-created_at
```

| Parameter | Default | Rules |
|-----------|---------|-------|
| `limit` | 20 | 1–100; outside that range → `422` |
| `offset` | 0 | ≥ 0 |
| `sort` | varies by endpoint | Field name; a `-` prefix means descending. Only listed fields are allowed |

Response envelope:

```json
{
  "items": [ ... ],
  "total": 134,
  "limit": 20,
  "offset": 40
}
```

Cursor-based pagination can replace offset later for very large collections; the envelope
would gain a `next_cursor` field.

### 1.7 Idempotency: why it matters for orders and payments

Networks fail *after* the server has done the work but *before* the client gets the reply.
A client that simply retries `POST /api/orders` or `POST /api/payments` could create **two
orders** or **charge the customer twice**.

ShopEase rules:
1. The client creates a unique `Idempotency-Key` (a UUID) per *intended* operation and reuses
   it on every retry of that operation.
2. The server stores the key with the result. A repeat with the **same key and same body**
   returns the **original response** without doing the work again.
3. Same key, **different body** → `409 IDEMPOTENCY_KEY_REUSED`.
4. A repeat while the first request is still processing → `409 REQUEST_IN_PROGRESS`; the
   client retries later.
5. Keys are kept for at least 24 hours.
6. Internal calls are idempotent by design too: stock reservations are unique per
   (`order_id`, `product_id`), and payments are unique per idempotency key.

Choosing the right method matters for the same reason. `GET`, `PUT` and `DELETE` can be
retried safely. `POST` cannot be, unless it is protected by an idempotency key.

### 1.8 Error format

Every error that ShopEase itself produces uses one envelope:

```json
{
  "error": {
    "code": "OUT_OF_STOCK",
    "message": "Only 2 units of 'Trail Running Shoe' are available.",
    "details": [ { "field": "items[0].quantity", "issue": "exceeds available stock (2)" } ],
    "request_id": "req-7f3a9c2e"
  }
}
```

- `code`: a stable, machine-readable value that clients can rely on.
- `message`: a human-readable explanation. It never contains stack traces, SQL or secrets.
- `details`: optional, a list of per-field problems.
- `request_id`: the correlation ID, for support and log searches.

### 1.9 Validation errors and FastAPI's default 422

FastAPI checks path parameters, query parameters, headers and request bodies against
Pydantic models **before** the endpoint code runs. When this check fails, FastAPI returns
**`422 Unprocessable Entity`** by default (not `400`), with this shape:

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "email"],
      "msg": "Field required",
      "input": { "password": "<redacted>", "full_name": "Asha Rao" }
    },
    {
      "type": "string_too_short",
      "loc": ["body", "password"],
      "msg": "String should have at least 12 characters",
      "input": "<redacted>",
      "ctx": { "min_length": 12 }
    }
  ]
}
```

Notes:
- This behavior holds **unless it is customized** with a custom
  `RequestValidationError` exception handler, which can change both the status code and the
  body shape.
- **Proposal (OPEN-14):** keep status **`422`**, but convert the body to the ShopEase error
  envelope, so clients handle a single format. The handler must also **remove raw input
  values**, because FastAPI's default `input` field would repeat passwords back to the client.

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed.",
    "details": [
      { "field": "body.email", "issue": "Field required" },
      { "field": "body.password", "issue": "String should have at least 12 characters" }
    ],
    "request_id": "req-1c9d4e7a"
  }
}
```

- `400 Bad Request` is kept for requests that can't be read at all, such as malformed JSON
  syntax. (FastAPI reports even that as `422` by default; the custom handler can map it to
  `400` with code `MALFORMED_JSON`.)
- **Business rule violations** that pass schema validation, but conflict with the current
  state, use `409` (for example, out of stock, or an invalid status change).

### 1.10 HTTP status codes

| Code | Name | When ShopEase uses it |
|------|------|------------------------|
| **200** | OK | Successful `GET`, `PUT`, `PATCH`, or an action that returns a result (login) |
| **201** | Created | A new resource was created; the `Location` header points to it |
| **202** | Accepted | The request was accepted but the outcome isn't final yet. Used for payments when the provider hasn't confirmed; the client checks the payment resource |
| **204** | No Content | Success with no body: `DELETE`, logout |
| **400** | Bad Request | Malformed request (bad JSON syntax, unreadable body) |
| **401** | Unauthorized | Missing, malformed or expired token, or wrong login credentials |
| **403** | Forbidden | Authenticated but not allowed (wrong role, someone else's resource, missing scope) |
| **404** | Not Found | The resource doesn't exist, or the caller isn't allowed to know it exists |
| **409** | Conflict | Conflicts with the current state: duplicate email, out of stock, invalid status change, idempotency conflict |
| **422** | Unprocessable Entity | Request validation failed (FastAPI default), or a payment was declined (`PAYMENT_DECLINED`) |
| **429** | Too Many Requests | Rate limit exceeded; includes `Retry-After` |
| **500** | Internal Server Error | Unexpected bug. The body is generic; details go to the logs only |
| **502** | Bad Gateway | An upstream service or the payment provider returned an invalid response |
| **503** | Service Unavailable | An upstream service is down or overloaded; may include `Retry-After` |
| **504** | Gateway Timeout | An upstream service didn't respond in time |

**`404` vs `403` for other users' resources:** when a customer requests *someone else's*
order or payment, ShopEase returns **`404`**, not `403`. This avoids confirming that the ID
exists. `403` is used when the caller lacks the role for an action (for example, a customer
calling an admin route).

---

## Part 2 — Path Conventions and Routing

- **Every public path starts with `/api/`** and the service name: `/api/auth/...`,
  `/api/users/...`, `/api/products/...`, `/api/categories`, `/api/orders/...`,
  `/api/payments/...` (proposed ADR-12).
- The gateway forwards each path **unchanged** to the owning service, so a service's own
  Swagger UI shows the same paths a client uses.
- `/api/categories` is served by product_service.
- `/internal/...` paths are **never** routed by the gateway (Part 4).
- Versioning: breaking changes would move to `/api/v2/...`. The current unversioned paths
  count as v1.

Gateway routing table:

| Path prefix | Service |
|-------------|---------|
| `/api/auth/` | auth_service |
| `/api/users/` | user_service |
| `/api/products/`, `/api/categories` | product_service |
| `/api/orders/` | order_service |
| `/api/payments/` | payment_service |
| `/internal/` | **blocked** (`404`) |

### Sample identifiers used below

| Entity | Sample ID |
|--------|-----------|
| User (Asha Rao) | `3f6c2a9e-8b1d-4c7a-9e2f-1a5b7c9d0e11` |
| Address | `7a1e4b2c-5d6f-4a8b-9c0d-2e3f4a5b6c71` |
| Category (Running Shoes) | `c1a2b3c4-d5e6-4f70-8a91-b2c3d4e5f601` |
| Product (Trail Running Shoe) | `9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c61` |
| Product (Running Socks 3-Pack) | `2d4f6a8c-0e1f-4b3d-9a5c-7e9f1b3d5a72` |
| Order | `5e7a9c1b-3d5f-4e7a-9b1c-3d5e7f9a1b21` |
| Payment | `8c0e2a4b-6d8f-4a0c-8e2b-4d6f8a0c2e41` |

---

## Part 3 — Endpoint Reference

### 3.1 API Gateway

The gateway has no business endpoints. It owns only its health check and the responses it
generates itself.

#### `GET /health`
- **Purpose:** liveness check for the gateway (each service has its own `/health`).
- **Auth:** Public.
- **Success `200`:**
```json
{ "service": "api_gateway", "status": "ok" }
```

#### Errors generated by the gateway (before or instead of reaching a service)

| Situation | Status | Example body |
|-----------|--------|--------------|
| Protected route without a valid token | `401` | `{"error": {"code": "UNAUTHENTICATED", "message": "A valid bearer token is required.", "request_id": "req-2b8e"}}` |
| Unknown route or `/internal/*` | `404` | `{"error": {"code": "ROUTE_NOT_FOUND", "message": "No route for GET /api/unknown.", "request_id": "req-2b8f"}}` |
| Request body over `MAX_REQUEST_BODY_BYTES` | `413` | `{"error": {"code": "PAYLOAD_TOO_LARGE", "message": "The request body is too large.", "request_id": "req-2b8d"}}` |
| Rate limit exceeded | `429` + `Retry-After: 30` | `{"error": {"code": "RATE_LIMITED", "message": "Too many requests. Retry after 30 seconds.", "request_id": "req-2b90"}}` |
| Upstream returned an invalid response | `502` | `{"error": {"code": "BAD_UPSTREAM_RESPONSE", "message": "The product service returned an invalid response.", "request_id": "req-2b91"}}` |
| Upstream unavailable | `503` | `{"error": {"code": "SERVICE_UNAVAILABLE", "message": "The order service is temporarily unavailable.", "request_id": "req-2b92"}}` |
| Upstream timeout | `504` | `{"error": {"code": "UPSTREAM_TIMEOUT", "message": "The payment service did not respond in time.", "request_id": "req-2b93"}}` |

Status codes produced by services themselves pass through the gateway unchanged, except an upstream
`5xx` without the ShopEase envelope, malformed JSON or an invalid status, which become `502`.
Full gateway behaviour and the verified route list: [api_gateway.md](api_gateway.md).

---

### 3.2 Authentication Service

#### `POST /api/auth/register`
- **Purpose:** create login credentials for a new customer.
- **Auth:** Public. Rate-limited strictly.
- **Request:**
```json
{
  "email": "asha.rao@example.com",
  "password": "<placeholder-password>"
}
```
- **Success `201`** + `Location: /api/users/me`:
```json
{
  "user_id": "3f6c2a9e-8b1d-4c7a-9e2f-1a5b7c9d0e11",
  "email": "asha.rao@example.com",
  "role": "customer",
  "created_at": "2026-10-29T10:15:30Z"
}
```
- **Status codes:** `201` · `409` email already registered · `422` validation (bad email, weak password) · `429` · `500`
- **Error `409`:**
```json
{ "error": { "code": "EMAIL_ALREADY_REGISTERED", "message": "An account with this email already exists.", "request_id": "req-4a1d" } }
```

> The response never contains the password or its hash. Whether to reveal "already
> registered" (account enumeration) versus always replying neutrally is a policy choice; the
> `409` shown here is the simpler option for Day 2. **Decided (2026-10-30): keep `409`**
> (ADR-16); revisit if email verification is added.

#### `POST /api/auth/login`
- **Purpose:** exchange credentials for tokens. This is an **action**, so it uses `POST` and returns `200`, not `201`.
- **Auth:** Public. Rate-limited per IP and per email; lockout after repeated failures.
- **Request:**
```json
{
  "email": "asha.rao@example.com",
  "password": "<placeholder-password>"
}
```
- **Success `200`:**
```json
{
  "access_token": "<jwt-access-token>",
  "token_type": "Bearer",
  "expires_in": 900,
  "refresh_token": "<opaque-refresh-token>"
}
```
- **Status codes:** `200` · `401` wrong credentials · `422` validation · `423`/`429` locked out or too many attempts · `500`
- **Error `401`** (the same message for an unknown email and a wrong password):
```json
{ "error": { "code": "INVALID_CREDENTIALS", "message": "Email or password is incorrect.", "request_id": "req-4a2e" } }
```

Other auth routes (contracts in [service_responsibilities.md](service_responsibilities.md)):
`POST /api/auth/refresh` (`200`), `POST /api/auth/logout` (`204`),
`GET /api/auth/.well-known/jwks.json` (`200`, public keys only).

---

### 3.3 User Service

#### `GET /api/users/me`
- **Purpose:** return the caller's profile. It is created empty on first access (ADR-09).
- **Auth:** Customer (the profile is chosen by the token's `sub`; no ID in the path).
- **Success `200`:**
```json
{
  "user_id": "3f6c2a9e-8b1d-4c7a-9e2f-1a5b7c9d0e11",
  "full_name": "Asha Rao",
  "phone": "+91-90000-00000",
  "contact_email": "asha.rao@example.com",
  "created_at": "2026-10-29T10:16:02Z",
  "updated_at": "2026-10-29T10:20:44Z"
}
```
- **Status codes:** `200` · `401` · `500`
- **Error `401`:**
```json
{ "error": { "code": "TOKEN_EXPIRED", "message": "The access token has expired.", "request_id": "req-5b3f" } }
```

`PATCH /api/users/me` updates only the fields sent, for example `{"phone": "+91-90000-00001"}` → `200` with the full profile.

#### `GET /api/users/me/addresses`
- **Purpose:** list the caller's delivery addresses.
- **Auth:** Customer (only the caller's own addresses are returned).
- **Query:** `limit`, `offset`.
- **Success `200`:**
```json
{
  "items": [
    {
      "address_id": "7a1e4b2c-5d6f-4a8b-9c0d-2e3f4a5b6c71",
      "label": "Home",
      "line1": "12 Example Street",
      "line2": "Flat 4B",
      "city": "Pune",
      "state": "Maharashtra",
      "postal_code": "411001",
      "country": "IN",
      "is_default": true
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```
- **Status codes:** `200` · `401` · `422` invalid pagination · `500`

Related: `POST /api/users/me/addresses` (`201`), `PUT /api/users/me/addresses/{address_id}`
(`200`, full replacement: every field is required), `DELETE /api/users/me/addresses/{address_id}`
(`204`; `404` if it isn't the caller's; `409 DEFAULT_ADDRESS_REQUIRED` if it's the only default address and orders depend on it).

---

### 3.4 Product Service

#### `GET /api/products`
- **Purpose:** browse and search the catalog.
- **Auth:** Public. Archived products are hidden from non-admins.
- **Query parameters:** `q` (text search), `category_id`, `min_price`, `max_price`, `in_stock` (bool), `sort` (`price`, `-price`, `name`, `-created_at`), `limit`, `offset`.
- **Example:** `GET /api/products?category_id=c1a2b3c4-d5e6-4f70-8a91-b2c3d4e5f601&in_stock=true&sort=price&limit=2`
- **Success `200`:**
```json
{
  "items": [
    {
      "product_id": "2d4f6a8c-0e1f-4b3d-9a5c-7e9f1b3d5a72",
      "sku": "SOCK-RUN-3PK",
      "name": "Running Socks 3-Pack",
      "price": "299.00",
      "currency": "INR",
      "category_id": "c1a2b3c4-d5e6-4f70-8a91-b2c3d4e5f601",
      "in_stock": true
    },
    {
      "product_id": "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c61",
      "sku": "SHOE-TRAIL-01",
      "name": "Trail Running Shoe",
      "price": "2499.00",
      "currency": "INR",
      "category_id": "c1a2b3c4-d5e6-4f70-8a91-b2c3d4e5f601",
      "in_stock": true
    }
  ],
  "total": 14,
  "limit": 2,
  "offset": 0
}
```
- **Status codes:** `200` · `422` invalid filter (e.g. `min_price` > `max_price`, `limit=500`) · `429` · `500`
- **Error `422`** (ShopEase envelope, as proposed):
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed.",
    "details": [ { "field": "query.limit", "issue": "Input should be less than or equal to 100" } ],
    "request_id": "req-6c40"
  }
}
```

#### `GET /api/products/{product_id}`
- **Purpose:** product details.
- **Auth:** Public.
- **Success `200`:**
```json
{
  "product_id": "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c61",
  "sku": "SHOE-TRAIL-01",
  "name": "Trail Running Shoe",
  "description": "Lightweight trail shoe with a grippy outsole.",
  "price": "2499.00",
  "currency": "INR",
  "category": { "category_id": "c1a2b3c4-d5e6-4f70-8a91-b2c3d4e5f601", "name": "Running Shoes" },
  "available_quantity": 37,
  "status": "ACTIVE",
  "updated_at": "2026-10-28T08:00:00Z"
}
```
- **Status codes:** `200` · `404` not found or archived · `422` `product_id` is not a valid UUID · `500`
- **Error `404`:**
```json
{ "error": { "code": "PRODUCT_NOT_FOUND", "message": "Product 9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c61 was not found.", "request_id": "req-6c41" } }
```

Admin routes: `POST /api/products` (`201`; `409 DUPLICATE_SKU`), `PATCH /api/products/{product_id}`
(`200`), `DELETE /api/products/{product_id}` (archives the product, `204`),
`PATCH /api/products/{product_id}/inventory` (`200`). A customer calling these gets `403 FORBIDDEN`.

#### `GET /api/categories`
- **Purpose:** list categories for navigation and filters.
- **Auth:** Public.
- **Success `200`:**
```json
{
  "items": [
    { "category_id": "c1a2b3c4-d5e6-4f70-8a91-b2c3d4e5f601", "name": "Running Shoes", "parent_id": null },
    { "category_id": "e7f8a9b0-c1d2-4e3f-9a4b-5c6d7e8f9a02", "name": "Accessories", "parent_id": null }
  ],
  "total": 2,
  "limit": 20,
  "offset": 0
}
```
- **Status codes:** `200` · `422` · `500`

#### Implemented contract details (2026-10-30)

**Catalog writes (admin; `401` without a token, `403 FORBIDDEN` for customers):**

| Method | Path | Body | Success | Errors |
|--------|------|------|---------|--------|
| POST | `/api/products` | `sku` (letters, digits, `._-`; stored upper-case), `name` (1–200), `description` (≤ 5000), `category_id`, `price` (> 0, 2 decimals), `currency` (ISO, default `INR`), `initial_stock` (0–1,000,000) | `201` + `Location` | `409 DUPLICATE_SKU` · `422 CATEGORY_NOT_FOUND` · `422 VALIDATION_ERROR` |
| PATCH | `/api/products/{product_id}` | any of `name`, `description`, `category_id`, `price`, `currency`, `status` (`ACTIVE`/`ARCHIVED`); SKU is immutable | `200` | `404 PRODUCT_NOT_FOUND` · `422` |
| DELETE | `/api/products/{product_id}` | — (archives; reactivate with PATCH `status`) | `204` | `404` |
| GET | `/api/products/{product_id}/inventory` | — | `200` `{quantity_on_hand, quantity_reserved, quantity_available, version}` | `404` |
| PATCH | `/api/products/{product_id}/inventory` | `{quantity_change, reason: RESTOCK or ADJUST, note?}`; RESTOCK must be positive | `200` | `409 INSUFFICIENT_STOCK` (would drop below reserved) · `422` |
| GET | `/api/products/{product_id}/inventory/movements` | `limit`, `offset` | `200` audit trail, newest first | `404` |
| POST | `/api/categories` | `{name (1–100, unique), parent_id?}` | `201` + `Location` | `409 DUPLICATE_CATEGORY` · `422 CATEGORY_NOT_FOUND` |
| PATCH | `/api/categories/{category_id}` | `{name?, parent_id?}` | `200` | `422 INVALID_CATEGORY_PARENT` (cycle) · `409` · `404` |
| DELETE | `/api/categories/{category_id}` | — | `204` | `409 CATEGORY_IN_USE` (has products or subcategories) · `404` |

Public reads: `GET /api/categories/{category_id}` (`200`, `404 CATEGORY_NOT_FOUND`) and
`GET /api/categories?parent_id=`. On `GET /api/products`, `q` searches name, SKU and
description (`%` and `_` are literal); `sort` accepts `price`, `-price`, `name`, `-name`,
`created_at`, `-created_at` (default `name`). Admins (valid admin token) also see archived
products and may filter with `status`. A token that is sent but invalid gets `401`, even on
public routes.

All Product Service routes answer `503 DATABASE_UNAVAILABLE` when product_db can't be
reached, and `503 SERVICE_BUSY` if stock rows stay locked after three attempts.

---

### 3.5 Order Service

#### `POST /api/orders`
- **Purpose:** place an order. order_service checks current prices, copies the address,
  reserves stock and creates the order in `AWAITING_PAYMENT`. The customer then pays with
  `POST /api/payments` (two-step checkout, ADR-13).
- **Auth:** Customer. The order belongs to the token's `sub`; a `user_id` in the body is
  not accepted.
- **Headers:** `Idempotency-Key` **required**.
- **Request:**
```json
{
  "items": [
    { "product_id": "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c61", "quantity": 1 },
    { "product_id": "2d4f6a8c-0e1f-4b3d-9a5c-7e9f1b3d5a72", "quantity": 2 }
  ],
  "shipping_address_id": "7a1e4b2c-5d6f-4a8b-9c0d-2e3f4a5b6c71"
}
```
- **Success `201`** + `Location: /api/orders/5e7a9c1b-3d5f-4e7a-9b1c-3d5e7f9a1b21`:
```json
{
  "order_id": "5e7a9c1b-3d5f-4e7a-9b1c-3d5e7f9a1b21",
  "status": "AWAITING_PAYMENT",
  "items": [
    { "product_id": "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c61", "name": "Trail Running Shoe", "unit_price": "2499.00", "quantity": 1, "line_total": "2499.00" },
    { "product_id": "2d4f6a8c-0e1f-4b3d-9a5c-7e9f1b3d5a72", "name": "Running Socks 3-Pack", "unit_price": "299.00", "quantity": 2, "line_total": "598.00" }
  ],
  "total_amount": "3097.00",
  "currency": "INR",
  "shipping_address": {
    "line1": "12 Example Street", "line2": "Flat 4B", "city": "Pune",
    "state": "Maharashtra", "postal_code": "411001", "country": "IN"
  },
  "payment_due_by": "2026-10-29T10:45:00Z",
  "created_at": "2026-10-29T10:30:00Z"
}
```
Prices come from product_service, never from the client. `payment_due_by` is when the stock
reservation expires.
- **Status codes:** `201` · `401` · `404` product or address not found (or not the caller's)
  · `409` out of stock / idempotency conflict · `422` validation (empty `items`,
  `quantity` < 1) · `429` · `502`/`503`/`504` a dependency failed · `500`
- **A retry with the same `Idempotency-Key` and body** returns the original `201` response;
  no second order is created.
- **Error `409`:**
```json
{
  "error": {
    "code": "OUT_OF_STOCK",
    "message": "Only 2 units of 'Trail Running Shoe' are available.",
    "details": [ { "field": "items[0].quantity", "issue": "exceeds available stock (2)" } ],
    "request_id": "req-7d52"
  }
}
```
- **Error `503`:**
```json
{ "error": { "code": "DEPENDENCY_UNAVAILABLE", "message": "Inventory is temporarily unavailable. Please retry.", "request_id": "req-7d53" } }
```

#### `GET /api/orders`
- **Purpose:** order history. Customers see their own orders; admins can see all.
- **Auth:** Customer (own orders) or Admin.
- **Query:** `status`, `created_from`, `created_to`, `sort` (default `-created_at`), `limit`, `offset`. Admins only: `user_id`.
- **Success `200`:**
```json
{
  "items": [
    {
      "order_id": "5e7a9c1b-3d5f-4e7a-9b1c-3d5e7f9a1b21",
      "status": "PAID",
      "total_amount": "3097.00",
      "currency": "INR",
      "item_count": 3,
      "created_at": "2026-10-29T10:30:00Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```
- **Status codes:** `200` · `401` · `403` a customer used the `user_id` filter · `422` invalid filter · `500`

#### `GET /api/orders/{order_id}`
- **Purpose:** full order details, including items and status history.
- **Auth:** Owner or Admin.
- **Success `200`:**
```json
{
  "order_id": "5e7a9c1b-3d5f-4e7a-9b1c-3d5e7f9a1b21",
  "status": "PAID",
  "items": [
    { "product_id": "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c61", "name": "Trail Running Shoe", "unit_price": "2499.00", "quantity": 1, "line_total": "2499.00" },
    { "product_id": "2d4f6a8c-0e1f-4b3d-9a5c-7e9f1b3d5a72", "name": "Running Socks 3-Pack", "unit_price": "299.00", "quantity": 2, "line_total": "598.00" }
  ],
  "total_amount": "3097.00",
  "currency": "INR",
  "payment_id": "8c0e2a4b-6d8f-4a0c-8e2b-4d6f8a0c2e41",
  "status_history": [
    { "from_status": null, "to_status": "PENDING", "changed_at": "2026-10-29T10:30:00Z" },
    { "from_status": "PENDING", "to_status": "AWAITING_PAYMENT", "changed_at": "2026-10-29T10:30:01Z" },
    { "from_status": "AWAITING_PAYMENT", "to_status": "PAID", "changed_at": "2026-10-29T10:31:12Z" }
  ],
  "created_at": "2026-10-29T10:30:00Z",
  "updated_at": "2026-10-29T10:31:12Z"
}
```
- **Status codes:** `200` · `401` · `404` not found **or someone else's order** · `422` invalid UUID · `500`

Related actions: `POST /api/orders/{order_id}/cancel` (`200`; owner only before payment;
`409 INVALID_STATUS_TRANSITION` otherwise), `PATCH /api/orders/{order_id}/status` (admin
fulfilment: `SHIPPED`, `DELIVERED`).

#### Implemented contract details (2026-10-30)

- `POST /api/orders`: `Idempotency-Key` must be 8–64 characters (`A-Z a-z 0-9 . _ : -`).
  The body accepts only `items` (1–50, unique `product_id`, `quantity` 1–100) and
  `shipping_address_id`; any price, total or `user_id` field is rejected with `422`. A replay
  returns `201` with `Idempotent-Replayed: true`. Responses also carry `payment_status`,
  `cancel_reason` and `status_history` (with `reason`).
- Errors: `404 PRODUCT_NOT_FOUND`, `404 ADDRESS_NOT_FOUND`, `409 OUT_OF_STOCK`,
  `409 PRODUCT_UNAVAILABLE`, `409 MIXED_CURRENCY`, `409 IDEMPOTENCY_KEY_REUSED`,
  `409 REQUEST_IN_PROGRESS`, `503 DEPENDENCY_UNAVAILABLE` / `504 DEPENDENCY_TIMEOUT`
  (before the order was stored: retry with the same key), `503 ORDER_NOT_PLACED` (replay of
  a key whose reservation failed: use a new key).
- `POST /api/orders/{order_id}/cancel` (owner or admin, `AWAITING_PAYMENT` only): releases
  the stock first. `409 PAYMENT_IN_PROGRESS` while a payment is `PROCESSING`/`SUCCEEDED`,
  `409 INVALID_STATUS_TRANSITION` for paid or cancelled orders, `409 REQUEST_IN_PROGRESS`
  for `PENDING`.
- `PATCH /api/orders/{order_id}/status` (admin): body `{"status": "SHIPPED" | "DELIVERED"}`.
- Full sequence, transitions and recovery: [order_workflow.md](order_workflow.md).

---

### 3.6 Payment Service

> **Two-step checkout (ADR-13, accepted).** The client creates the
> order, then pays for it with `POST /api/payments`. This replaces ADR-10. The amount is never
> taken from the client: payment_service gets the payable amount from order_service.

#### `POST /api/payments`
- **Purpose:** pay for an existing order that is in `AWAITING_PAYMENT`.
- **Auth:** Owner of the order.
- **Headers:** `Idempotency-Key` **required**. A retry must never cause a second charge.
- **Request:** the payment method is an **opaque token** issued by the payment provider's
  client-side SDK. ShopEase never receives card numbers or CVVs.
```json
{
  "order_id": "5e7a9c1b-3d5f-4e7a-9b1c-3d5e7f9a1b21",
  "payment_method_token": "<provider-payment-method-token>"
}
```
No `amount` field: the amount comes from the order, never from the client.
- **Success `201`** (the provider confirmed right away) + `Location: /api/payments/8c0e2a4b-6d8f-4a0c-8e2b-4d6f8a0c2e41`:
```json
{
  "payment_id": "8c0e2a4b-6d8f-4a0c-8e2b-4d6f8a0c2e41",
  "order_id": "5e7a9c1b-3d5f-4e7a-9b1c-3d5e7f9a1b21",
  "status": "SUCCEEDED",
  "amount": "3097.00",
  "currency": "INR",
  "payment_method": { "type": "card", "brand": "VISA" },
  "provider_reference": "sim_txn_000123",
  "created_at": "2026-10-29T10:31:10Z"
}
```
- **Accepted `202`** (the provider hasn't confirmed yet) + `Location: /api/payments/8c0e2a4b-6d8f-4a0c-8e2b-4d6f8a0c2e41`:
```json
{
  "payment_id": "8c0e2a4b-6d8f-4a0c-8e2b-4d6f8a0c2e41",
  "order_id": "5e7a9c1b-3d5f-4e7a-9b1c-3d5e7f9a1b21",
  "status": "PROCESSING",
  "amount": "3097.00",
  "currency": "INR",
  "created_at": "2026-10-29T10:31:10Z"
}
```
The client checks `GET /api/payments/{payment_id}` until the status is `SUCCEEDED` or `FAILED`.
- **Status codes:** `201` · `202` · `401` · `404` order not found or not the caller's ·
  `409` order not in `AWAITING_PAYMENT` / already paid / reservation expired / idempotency
  conflict · `422` validation, or `PAYMENT_DECLINED` · `429` · `502` invalid provider response
  · `503` provider or order service unavailable · `504` provider timeout · `500`
- **Error `422` (declined):**
```json
{ "error": { "code": "PAYMENT_DECLINED", "message": "The payment was declined by the provider.", "request_id": "req-8e64" } }
```
- **Error `409`:**
```json
{ "error": { "code": "ORDER_NOT_PAYABLE", "message": "Order 5e7a9c1b-3d5f-4e7a-9b1c-3d5e7f9a1b21 is already PAID.", "request_id": "req-8e65" } }
```
- **Timeouts:** if the client gets no response, it **retries with the same
  `Idempotency-Key`**. It must never make a new key for the same payment attempt, or it
  could be charged twice.

#### `GET /api/payments/{payment_id}`
- **Purpose:** payment status and details.
- **Auth:** Owner or Admin.
- **Success `200`:**
```json
{
  "payment_id": "8c0e2a4b-6d8f-4a0c-8e2b-4d6f8a0c2e41",
  "order_id": "5e7a9c1b-3d5f-4e7a-9b1c-3d5e7f9a1b21",
  "status": "SUCCEEDED",
  "amount": "3097.00",
  "currency": "INR",
  "payment_method": { "type": "card", "brand": "VISA" },
  "provider_reference": "sim_txn_000123",
  "refunds": [],
  "created_at": "2026-10-29T10:31:10Z",
  "updated_at": "2026-10-29T10:31:12Z"
}
```
- **Status codes:** `200` · `401` · `404` not found or someone else's payment · `422` invalid UUID · `500`

Related: `GET /api/payments?order_id=...` (`200`, the caller's payments for one order);
`POST /api/payments/{payment_id}/refunds` (Admin; `201` refund created, `202` refund pending,
`409 PAYMENT_NOT_REFUNDABLE`); `POST /api/payments/webhooks/{provider}` (provider only,
authenticated by signature, `200`/`400`).

#### Implemented contract details (2026-10-30)

- **Mock provider only** (development and tests): see [payment_processing.md](payment_processing.md) §4
  for the `mock_tok_*` tokens. Card numbers are rejected.
- `POST /api/payments` body: `order_id`, `payment_method_token` (8–128 chars, letters, digits,
  `_`, `-`), optional `expected_amount` and `currency` that must equal the order's
  (`409 AMOUNT_MISMATCH` / `CURRENCY_MISMATCH`). Answers: `201 SUCCEEDED`, `202 PROCESSING`,
  `422 PAYMENT_DECLINED`, `422 INVALID_PAYMENT_METHOD`, `404 ORDER_NOT_FOUND` (missing or not
  the caller's), `409 ORDER_NOT_PAYABLE`, `409 PAYMENT_ALREADY_IN_PROGRESS`,
  `409 IDEMPOTENCY_KEY_REUSED`, `409 ORDER_NOT_FULFILLABLE` (charged, then refunded),
  `503 PAYMENT_PROVIDER_UNAVAILABLE` (nothing charged), `503`/`504` order_service unavailable
  (nothing charged). A replay with the same key returns the stored outcome.
- Payment responses include `provider`, `payment_method {type, brand, last4}`,
  `provider_reference`, `failure_reason`, `requires_review`, `refunds` and `status_history`.
- `POST /api/payments/{payment_id}/refunds` (admin) requires an `Idempotency-Key`; body
  `{amount?, reason?}`; `201` refunded, `202` outcome unknown, `409 PAYMENT_NOT_REFUNDABLE`.
- `POST /internal/payments/{payment_id}/reconcile` (service token, scope
  `payments:reconcile`; `?include_manual_review=true` to retry flagged payments): asks the
  provider for the outcome; never charges.
- `POST /api/payments/webhooks/{provider}` answers `501 WEBHOOKS_NOT_SUPPORTED` (mock).

#### Service calls behind the payment endpoints
- payment_service → order_service: gets the payable amount (`GET /internal/orders/{order_id}/payable`)
  and reports the result (`POST /internal/orders/{order_id}/payment-result`). order_service then
  confirms or releases the stock reservation.
- order_service **never calls** payment_service, which keeps the dependency graph acyclic
  (ADR-11). Refunds are started on payment_service, which then tells order_service.
- The full workflow, timeouts and failure flows are in
  [service_communication.md](service_communication.md).

---

## Part 4 — Internal Endpoints (not routed by the gateway)

These need a service token with the listed scope (ADR-08) and are never reachable by
clients.

```
POST /internal/auth/service-token                    client credentials (any service -> auth)
POST /internal/products/price-check                  products:read      (order -> product)
POST /internal/reservations                          inventory:reserve  (order -> product)
POST /internal/reservations/{order_id}/confirm       inventory:reserve  (order -> product)
POST /internal/reservations/{order_id}/release       inventory:reserve  (order -> product)
GET  /internal/users/{user_id}/addresses/{address_id} addresses:read    (order -> user)
GET  /internal/orders/{order_id}/payable             orders:read        (payment -> order)
POST /internal/orders/{order_id}/payment-result      orders:payment     (payment -> order)
```

### Product Service internal contracts (implemented 2026-10-30)

| Endpoint | Request | Success | Errors |
|----------|---------|---------|--------|
| `POST /internal/products/price-check` | `{"product_ids": [uuid, ...]}` (1–100, unique) | `200 {"items": [{product_id, sku, name, price, currency, status, available_quantity, orderable}], "missing": [uuid]}` | `422` |
| `POST /internal/reservations` | `{"order_id", "items": [{"product_id", "quantity" (1–1000)}] (1–50, unique), "ttl_seconds"? (60–7200, default RESERVATION_TTL_MINUTES)}` | `201 {"order_id", "status": "RESERVED", "expires_at", "items": [...]}`; **`200`** with the same body when the order already holds this exact reservation (replay) | `409 OUT_OF_STOCK` (nothing reserved; `details` per item) · `409 PRODUCT_UNAVAILABLE` (archived) · `409 RESERVATION_CONFLICT` (order holds a different reservation) · `404 PRODUCT_NOT_FOUND` |
| `POST /internal/reservations/{order_id}/confirm` | — | `200`, status `CONFIRMED` (repeat calls return the same) | `404 RESERVATION_NOT_FOUND` · `409 RESERVATION_EXPIRED` (released, expired, or past `expires_at`; stock is returned) |
| `POST /internal/reservations/{order_id}/release` | — | `200 {"order_id", "released_items": n}`; `0` when nothing is held (safe after a reserve timeout) | `409 RESERVATION_ALREADY_CONFIRMED` |

Reservations are all-or-nothing across items and keyed by `order_id`, so every call can be
retried. Unconfirmed reservations past `expires_at` are released by a background job every
`RESERVATION_SWEEP_SECONDS`. Concurrency design: ADR-17.

### Order Service internal contracts (implemented 2026-10-30)

| Endpoint | Request | Success | Errors |
|----------|---------|---------|--------|
| `GET /internal/orders/{order_id}/payable` | — | `200 {order_id, user_id, status, payment_status, payable, amount, currency, payment_due_by}`; `payable` is true only for `AWAITING_PAYMENT` before `payment_due_by` | `404 ORDER_NOT_FOUND` |
| `POST /internal/orders/{order_id}/payment-result` | `{"payment_id", "outcome": "SUCCEEDED" \| "FAILED" \| "PROCESSING" \| "REFUNDED", "reason"?}` | `200 {order_id, status, payment_status}`. Idempotent: the same report again gives the same answer | `409 ORDER_NOT_FULFILLABLE` (expired or cancelled: **refund**) · `409 ORDER_ALREADY_PAID` (another payment won: **refund**) · `503`/`504` (stock confirmation unknown: report again later) · `404` |

---

## Part 5 — Summary of Proposed Public Routes

| Method | Path | Service | Access | Success |
|--------|------|---------|--------|---------|
| GET | `/health` | gateway | Public | 200 |
| POST | `/api/auth/register` | auth | Public | 201 |
| POST | `/api/auth/login` | auth | Public | 200 |
| POST | `/api/auth/refresh` | auth | Public (refresh token) | 200 |
| POST | `/api/auth/logout` | auth | Customer | 204 |
| PUT | `/api/auth/password` | auth | Customer | 204 |
| GET | `/api/auth/.well-known/jwks.json` | auth | Public | 200 |
| PATCH | `/api/auth/users/{user_id}/role` | auth | Admin | 200 |
| GET | `/api/users/me` | user | Customer | 200 |
| PATCH | `/api/users/me` | user | Customer | 200 |
| GET | `/api/users/me/addresses` | user | Customer | 200 |
| POST | `/api/users/me/addresses` | user | Customer | 201 |
| PUT | `/api/users/me/addresses/{address_id}` | user | Owner | 200 |
| DELETE | `/api/users/me/addresses/{address_id}` | user | Owner | 204 |
| GET | `/api/users/{user_id}` | user | Admin | 200 |
| GET | `/api/products` | product | Public | 200 |
| GET | `/api/products/{product_id}` | product | Public | 200 |
| POST | `/api/products` | product | Admin | 201 |
| PATCH | `/api/products/{product_id}` | product | Admin | 200 |
| DELETE | `/api/products/{product_id}` (archive) | product | Admin | 204 |
| PATCH | `/api/products/{product_id}/inventory` | product | Admin | 200 |
| GET | `/api/categories` | product | Public | 200 |
| GET | `/api/categories/{category_id}` | product | Public | 200 |
| POST | `/api/categories` | product | Admin | 201 |
| PATCH | `/api/categories/{category_id}` | product | Admin | 200 |
| DELETE | `/api/categories/{category_id}` | product | Admin | 204 |
| GET | `/api/products/{product_id}/inventory` | product | Admin | 200 |
| GET | `/api/products/{product_id}/inventory/movements` | product | Admin | 200 |
| POST | `/api/orders` | order | Customer + Idempotency-Key | 201 |
| GET | `/api/orders` | order | Customer (own) / Admin | 200 |
| GET | `/api/orders/{order_id}` | order | Owner / Admin | 200 |
| POST | `/api/orders/{order_id}/cancel` | order | Owner / Admin | 200 |
| PATCH | `/api/orders/{order_id}/status` | order | Admin | 200 |
| POST | `/api/payments` | payment | Owner + Idempotency-Key (ADR-13) | 201 / 202 |
| GET | `/api/payments/{payment_id}` | payment | Owner / Admin | 200 |
| GET | `/api/payments?order_id=` | payment | Owner / Admin | 200 |
| POST | `/api/payments/{payment_id}/refunds` | payment | Admin | 201 / 202 |
| POST | `/api/payments/webhooks/{provider}` | payment | Provider signature | 200 |

Every service also exposes `GET /health` on its own port. In development, interactive docs
are at `http://localhost:<port>/docs` (Swagger UI).
