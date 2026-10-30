# API Gateway

The single client-facing entry point (port 8000). FastAPI, as in the approved architecture.
It routes, authenticates at the edge, rate-limits and hides internal details. It holds **no
business logic and connects to no database**. Code: `api_gateway/app/` (`config.py` route map
and settings, `edge.py` public routes and rate limiting, `proxy.py` forwarding, `main.py`).

Related: [security_model.md](security_model.md) · [rest_api_notes.md](rest_api_notes.md) (contracts).

---

## 1. Route map

| Path prefix | Service | URL setting | Read timeout | Notes |
|-------------|---------|-------------|--------------|-------|
| `/api/auth` | auth_service | `AUTH_SERVICE_URL` | 5s (`UPSTREAM_TIMEOUT_SECONDS`) | |
| `/api/users` | user_service | `USER_SERVICE_URL` | 5s | |
| `/api/products` | product_service | `PRODUCT_SERVICE_URL` | 5s | |
| `/api/categories` | product_service | `PRODUCT_SERVICE_URL` | 5s | |
| `/api/orders` | order_service | `ORDER_SERVICE_URL` | 10s (`ORDER_UPSTREAM_TIMEOUT_SECONDS`) | order_service's own deadline is 7s plus compensation |
| `/api/payments` | payment_service | `PAYMENT_SERVICE_URL` | 20s (`PAYMENT_UPSTREAM_TIMEOUT_SECONDS`) | room for a real provider's ~10s charge |
| `/internal/*` | **never routed** | — | — | `404 ROUTE_NOT_FOUND` |
| anything else | — | — | — | `404 ROUTE_NOT_FOUND` |

Connect timeout: 1s (`UPSTREAM_CONNECT_TIMEOUT_SECONDS`). Paths are forwarded **unchanged**,
so each service's Swagger UI shows the same paths clients use. The gateway's own endpoints:
`GET /health` (liveness) and `GET /health/ready` (every upstream's `/health`).

## 2. Request handling, in order

1. **Request ID:** an incoming safe `X-Request-ID` is kept, otherwise `req-<hex>` is created;
   it is forwarded upstream and returned on every response.
2. **Route:** prefix match against the route map, else `404`.
3. **Rate limit** per client IP (TCP peer; `X-Forwarded-For` from clients is not trusted):
   `RATE_LIMIT_AUTH_PER_MINUTE` (20) for `POST /api/auth/register|login|refresh`,
   `RATE_LIMIT_DEFAULT_PER_MINUTE` (0 = off) for everything else → `429 RATE_LIMITED` + `Retry-After`.
4. **Edge authentication** on every non-public route: a genuine, unexpired RS256 access token
   (JWKS from auth_service, cached) → otherwise `401 UNAUTHENTICATED / INVALID_TOKEN / TOKEN_EXPIRED`.
   The gateway does **not** authorize (roles, ownership, scopes): every service does that itself.
5. **Body limit:** `MAX_REQUEST_BODY_BYTES` (1 MiB) → `413 PAYLOAD_TOO_LARGE`.
6. **Forward:** method, path, query string, body and headers unchanged, except:
   - removed: hop-by-hop headers, `Host`, `Content-Length` (recomputed), `Forwarded`,
     `X-Real-IP`, and every `X-User-*`, `X-Internal-*`, `X-Service-*`, `X-Forwarded-*`
     header (so clients can't impersonate a user or an internal caller);
   - set: `X-Request-ID`, `X-Forwarded-For` (the TCP peer), `X-Forwarded-Proto`.
7. **Response:** status, body and headers pass through unchanged, except:
   - an upstream **5xx that isn't a ShopEase error envelope** (crash page, proxy error) →
     `502 BAD_UPSTREAM_RESPONSE` (the original body is never shown);
   - a body declared as JSON that doesn't parse, or a status outside 200–599 → `502`;
   - a `Location` pointing at an internal service URL is rewritten to the path;
   - `Server`, `X-Powered-By`, `Via` are dropped.

**CORS** is enabled only when `CORS_ALLOWED_ORIGINS` lists origins (no credentials; allowed
headers `Authorization`, `Content-Type`, `Idempotency-Key`, `X-Request-ID`; exposed
`X-Request-ID`, `Location`, `Retry-After`).

## 3. Upstream failures

| Situation | Gateway answer | Retried? |
|-----------|----------------|----------|
| Service not running / refused / DNS failure | `503 SERVICE_UNAVAILABLE` + `Retry-After: 2` | Once, for `GET`/`HEAD` only (the request never arrived) |
| No response within the route's read timeout | `504 UPSTREAM_TIMEOUT` | Never (it may have been processed) |
| Broken HTTP, malformed JSON, invalid status, unstructured 5xx | `502 BAD_UPSTREAM_RESPONSE` | Never |
| Service's own error (`4xx`, envelope `5xx`) | passed through unchanged | — |

Gateway errors use the standard envelope `{"error": {"code", "message", "request_id"}}`.
Messages name the service in plain words ("The order service is temporarily unavailable.")
but never include URLs, hosts, ports, exception text or stack traces.

**Logging:** one access line per request (method, path, status, duration, request ID) and one
`upstream call` line per forward (service name, status or failure kind, duration, attempt).
No query strings, headers, tokens or URLs. The HTTP client libraries' own request logs
(which include full URLs) are silenced in every service (`shopease_shared.log_config`).

## 4. Public endpoints

Every `/api/*` route of every service, read from the services' live OpenAPI schemas and
exercised **through the gateway** against real services and MySQL on 2026-10-30
(`Verified` = the expected success status was returned). **Access** is enforced by the
service; **Edge** is what the gateway checks first.

| Method | Path | Service | Edge | Access | Verified |
|--------|------|---------|------|--------|----------|
| POST | `/api/auth/register` | auth | public, rate-limited | Public | 201 |
| POST | `/api/auth/login` | auth | public, rate-limited | Public | 200 |
| POST | `/api/auth/refresh` | auth | public, rate-limited | Refresh token | 200 |
| POST | `/api/auth/logout` | auth | token | Customer | 204 |
| PUT | `/api/auth/password` | auth | token | Customer | 204 |
| GET | `/api/auth/.well-known/jwks.json` | auth | public | Public | 200 |
| PATCH | `/api/auth/users/{user_id}/role` | auth | token | Admin | 200 |
| GET | `/api/users/me` | user | token | Customer | 200 |
| PATCH | `/api/users/me` | user | token | Customer | 200 |
| GET | `/api/users/me/addresses` | user | token | Customer | 200 |
| POST | `/api/users/me/addresses` | user | token | Customer | 201 |
| PUT | `/api/users/me/addresses/{address_id}` | user | token | Owner | 200 |
| DELETE | `/api/users/me/addresses/{address_id}` | user | token | Owner | 204 |
| GET | `/api/users/{user_id}` | user | token | Admin | 200 |
| GET | `/api/products` | product | public | Public (admins also see archived) | 200 |
| GET | `/api/products/{product_id}` | product | public | Public | 200 |
| POST | `/api/products` | product | token | Admin | 201 |
| PATCH | `/api/products/{product_id}` | product | token | Admin | 200 |
| DELETE | `/api/products/{product_id}` | product | token | Admin (archives) | 204 |
| GET | `/api/products/{product_id}/inventory` | product | token | Admin | 200 |
| PATCH | `/api/products/{product_id}/inventory` | product | token | Admin | 200 |
| GET | `/api/products/{product_id}/inventory/movements` | product | token | Admin | 200 |
| GET | `/api/categories` | product | public | Public | 200 |
| GET | `/api/categories/{category_id}` | product | public | Public | 200 |
| POST | `/api/categories` | product | token | Admin | 201 |
| PATCH | `/api/categories/{category_id}` | product | token | Admin | 200 |
| DELETE | `/api/categories/{category_id}` | product | token | Admin | 204 |
| POST | `/api/orders` | order | token | Customer + `Idempotency-Key` | 201 (and 409 out of stock) |
| GET | `/api/orders` | order | token | Customer (own) / Admin | 200 |
| GET | `/api/orders/{order_id}` | order | token | Owner / Admin | 200 |
| POST | `/api/orders/{order_id}/cancel` | order | token | Owner / Admin | 200 |
| PATCH | `/api/orders/{order_id}/status` | order | token | Admin | 200 |
| POST | `/api/payments` | payment | token | Owner + `Idempotency-Key` (**mock provider**) | 201 |
| GET | `/api/payments` | payment | token | Customer (own) / Admin | 200 |
| GET | `/api/payments/{payment_id}` | payment | token | Owner / Admin | 200 |
| POST | `/api/payments/{payment_id}/refunds` | payment | token | Admin + `Idempotency-Key` | 201 |
| POST | `/api/payments/webhooks/{provider}` | payment | public (provider signature) | — | **Not integrated**: `501` by design, the mock provider sends no webhooks |

36 of 37 routes integrated. All 28 token-protected routes were also called without a token
and rejected at the gateway with `401 UNAUTHENTICATED`.
