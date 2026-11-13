# JWT Integration with the ShopEase Authentication Service

| | |
|---|---|
| Task | 5: integrate the existing ShopEase Authentication Service |
| Date | 12 November 2026 |
| Authentication Service | `shopease-auth-service` v0.1.0, running at `127.0.0.1:8001`, **not modified** |
| Catalog code | `app/core/security.py` |
| Tests | `tests/test_auth_integration.py` (35), `tests/test_security.py` (36) |
| Evidence | `Test_Results/auth_integration_logs/` (logs 01–03) |

## 1. Summary

The Catalog Service has no login, registration, passwords or JWT secret. For each request that
carries a token, it sends the token to the Authentication Service's own endpoint,
`POST /api/auth/verify-token`. It trusts only that endpoint's answer: who the user is, their
current role, and whether they are active.

| Requirement | Result |
|---|---|
| Bearer token taken from the `Authorization` header | Done (`HTTPBearer`, own 401 for anything else) |
| Validated with the Authentication Service's mechanism | Done: its `verify-token` endpoint |
| User ID and role extracted | Done: `AuthenticatedUser.auth_user_id`, `.role` |
| 401 for missing, expired or invalid tokens | Done, tested |
| 403 for a missing role | Done, tested |
| ADMIN manages products, categories and inventory | Done, tested |
| Customers view active products and categories | Done, tested (the customer role is `USER`, see §2.2) |
| All administrative operations protected | Done: 11 routes, all tested for 401 and 403 |
| Fail closed | Done: no answer from the Authentication Service means no access |
| Authentication Service down handled and documented | Done: 503, see §6 |

## 2. What the Authentication Service actually does

These facts come from reading its code, not from assumptions.

| Item | Actual implementation | Source in `shopease-auth-service` |
|---|---|---|
| Signing algorithm | HMAC, `JWT_ALGORITHM`, default **HS256** (HS384/HS512 allowed) | `app/core/config.py` |
| Key | One shared secret, `JWT_SECRET_KEY`, at least 32 characters, no default. No public key. | `app/core/config.py` |
| Claims | `sub` (user ID as a string), `role`, `iat`, `exp` | `create_access_token` in `app/core/security.py` |
| User ID claim | `sub`, must be a whole number | `decode_access_token` |
| Role claim | `role`, a non-empty string | `decode_access_token` |
| Lifetime | `ACCESS_TOKEN_EXPIRE_MINUTES`, default **30** (1–1440). No refresh tokens. | `app/core/config.py`, README |
| Expired token | Rejected with 401 `Could not validate credentials` | `decode_access_token` (python-jose checks `exp`) |
| Verification endpoint | `POST /api/auth/verify-token`, no body, `Authorization: Bearer <token>` | `app/routers/auth_routes.py` |
| Verification answer | 200 `{"valid": true, "user": {"id", "full_name", "email", "role", "is_active"}}`; 401 for a missing, invalid or expired token or a deleted user; 403 `Inactive user` | `get_current_user`, `TokenVerificationResponse` |
| Role used in the answer | The role **from its database**, not the token's `role` claim | `get_current_user` |
| Login response | `{"message", "access_token", "token_type": "bearer", "user"}` | `POST /api/auth/login` |

### 2.1 Why the token is verified remotely

The tokens are HS256, signed with a shared secret. Checking a signature locally would mean
copying `JWT_SECRET_KEY` into this service. That secret can **create** tokens as well as check
them, so a copy here would let anyone who reads this service's configuration mint an ADMIN
token. Remote verification also gives two things a local check cannot:

- A deactivated or deleted user is refused at once, not when the token expires.
- A role change takes effect at once, because the role comes from the Authentication
  Service's database.

The cost is one HTTP call per authenticated request (see §8).

### 2.2 Roles: there is no `CUSTOMER` role

The Authentication Service stores a free-text `role` column with two values in use:

| Role | Meaning | How a user gets it |
|---|---|---|
| `USER` | Default for every registered account: the shop's customers | Registration (`DEFAULT_ROLE = "USER"`) |
| `ADMIN` | Administrator | A direct database change; the API has no endpoint for it (its README, "Known limitations") |

Migration `12ee6f689116` renamed the older value `customer` to `USER`. A read-only count of its
live database (12 November 2026) found 14 active users, all `USER`, and no `ADMIN`.

The Catalog Service therefore uses `CUSTOMER_ROLE = "USER"` and `ADMIN_ROLE = "ADMIN"`. It does not
invent a `CUSTOMER` role. Roles are compared exactly, so `admin` or `Admin` is **not** an admin.

## 3. How a request is checked

```
Client ──Bearer token──▶ Catalog Service ──same token──▶ Authentication Service
                         1. header present, scheme Bearer?        POST /api/auth/verify-token
                         2. ≤ 4096 chars, well-formed JWT,         checks signature, exp, claims,
                            header alg == JWT_ALGORITHM?           user exists and is active
                            (no secret; can only reject)
                         3. send token  ─────────────────────────▶
                         4. ◀── 200 {valid, user{id, role, is_active}} / 401 / 403 / anything else
                         5. role check for the route
```

- Steps 1–2 reject obviously bad tokens (none sent, wrong scheme, garbage, `alg: none`, another
  algorithm) without a network call. They never accept a token.
- Step 4 accepts only a 200 whose body has the exact expected shape. The user ID must be a positive
  integer that fits the database. A boolean, for example, is refused.
- The token is never logged, stored or returned. Logs record only error class names and status codes.
- Redirects are not followed, so the token cannot be sent to another address.

## 4. Reusable dependencies (`app/core/security.py`)

| Dependency | Use | Result |
|---|---|---|
| `get_current_authenticated_user` | Any route that needs a logged-in user | `AuthenticatedUser(auth_user_id, full_name, email, role)` or 401/403/503 |
| `get_optional_user` | Public routes | `None` without a token; a sent token is still verified, and a bad one is 401, never silently ignored |
| `require_roles(*roles)` | Factory for role-restricted routes | 403 `Admin role required`, or `One of these roles is required: ...` |
| `require_admin` | `require_roles("ADMIN")`; all writes and the whole inventory router | as above |
| `ensure_admin_for_inactive(include_inactive, user)` | Public listings with `include_inactive=true` | 401 without a token, 403 for non-admins |

Example:

```python
from fastapi import Depends
from app.core.security import ADMIN_ROLE, require_roles

@router.post("/things", dependencies=[Depends(require_roles(ADMIN_ROLE))])
def create_thing(...): ...
```

## 5. Access rules

| Operation | Anonymous | Customer (`USER`) | `ADMIN` |
|---|---|---|---|
| List and view active categories and products | 200 | 200 | 200 |
| View inactive records (`include_inactive=true`) | 401 | 403 | 200 |
| View an inactive product without `include_inactive` | 404 | 404 | 404 |
| Create, update, delete categories | 401 | 403 | 2xx |
| Create, update, deactivate products | 401 | 403 | 2xx |
| All `/api/inventory` routes (stock, stock-in, stock-out, history, low stock) | 401 | 403 | 2xx |

Browsing stays public, as decided in Task 1: customers do not need to log in to see the catalog.
Customers who are logged in get exactly the same view.

### Status codes

| Status | Body | When |
|---|---|---|
| 401 + `WWW-Authenticate: Bearer` | `Could not validate credentials` | No token, wrong scheme, malformed, wrong signature, altered, `alg: none`, **expired**, missing claims, unknown user |
| 403 | `Inactive user` | Valid token, but the account is deactivated |
| 403 | `Admin role required` | Valid token, role is not ADMIN |
| 503 | `Authentication service unavailable` | The Authentication Service gave no usable answer (§6) |

The 401 body is the same for every cause, as in the Authentication Service, so a caller cannot tell
why a token was refused.

## 6. When the Authentication Service is unavailable

Verification **fails closed**. If the answer is not a clear "yes", the request is refused.

| Situation | Catalog response |
|---|---|
| Connection refused, DNS failure | 503 |
| No answer within `AUTH_SERVICE_TIMEOUT_SECONDS` (default 5) | 503 |
| Authentication Service returns 5xx | 503 |
| 404 or 3xx (usually a wrong `AUTH_SERVICE_VERIFY_URL`) | 503; redirects are not followed |
| 200 that is not JSON or lacks fields | 503 |
| 200 with `"valid": false` or `"is_active": false` | 401 / 403 (the real service never sends these, but they are handled) |

Effects during an outage:

- **Admin operations stop** (503). No write or stock movement is made without verification.
- **A token sent to a public route gets 503.** The token cannot be checked, so it is not
  quietly downgraded to anonymous access.
- **Anonymous browsing keeps working.** Requests without a token never call the
  Authentication Service.
- 503, not 401, tells clients that their token is not at fault and that they can retry later.
  The cause is logged as an error class name or status code, never with the token.

Running both services: in Docker, the Catalog Service reaches the Authentication Service through
`DOCKER_AUTH_SERVICE_VERIFY_URL` (default `http://host.docker.internal:8001/api/auth/verify-token`).
Run locally, it uses `AUTH_SERVICE_VERIFY_URL` (`http://127.0.0.1:8001/...`).

## 7. Tests

### 7.1 Automated tests

`tests/test_auth_integration.py` does **not** replace the authentication dependencies. Requests
carry real `Authorization` headers, and the Catalog Service sends them over HTTP to a stand-in for
`verify-token`. The stand-in copies the Authentication Service's own logic:

- HS256 with a secret the Catalog Service never sees
- `sub`, `iat` and `exp` required, and `exp` checked
- `sub` numeric, `role` a non-empty string
- a user lookup: unknown is 401, inactive is 403
- the role taken from its user table

| Area | Tests |
|---|---|
| Missing tokens | No header on all 11 admin routes (401, and no call to the Authentication Service); empty header, `Bearer` with no token, Basic, other schemes |
| Invalid tokens | Garbage, wrong signing key, payload altered to ADMIN, `alg: none`, unknown user, no `exp`/`iat`, non-numeric `sub`; also refused on public routes |
| Expired tokens | Expired a minute ago: 401 on all 11 admin routes and on a public route, with the rejection confirmed to be because of `exp`; a token with 30 s left still works |
| ADMIN access | Full category, product and inventory cycle; sees inactive records |
| Customer (`USER`) access | Sees active categories and products only; inactive product 404; `include_inactive` 403; all 11 admin routes 403, with nothing changed |
| Role source | Token claims ADMIN but the database role is USER (demoted): 403; lower-case `admin`: 403; inactive user: 403 |
| Unavailable | Down, timeout, 500, 503, 404, redirect, non-JSON, incomplete JSON: all 503 on admin routes and on a public route with a token, while anonymous browsing gets 200; the token appears in no log or response |
| `require_roles` | Empty role list refused; the multi-role message |

`tests/test_security.py` (existing) adds unit tests of `verify_access_token`, the local pre-check
and the access rules.

**Results** (log 03): 71 passed for the two authentication modules. The whole suite gave
**214 passed** on SQLite and **214 passed** on the MySQL 8.4 test database.

**Checking the tests can fail:** with the role check disabled in a scratch run, 4 tests failed.
The code was then restored, and all tests passed again.

### 7.2 Live check against the running Authentication Service

`python -m scripts.auth_integration_check` (log 01) runs against the **real** Authentication
Service and the Catalog Service container on port 8006. It creates nothing in either service.
**16 passed, 0 failed.**

| Check | Result |
|---|---|
| Both services healthy | 200 |
| Real `verify-token`: no token / forged HS256 token / expired forged token | 401 / 401 / 401 |
| Catalog: anonymous browsing of products and categories | 200 |
| Catalog: no token, Basic, garbage, `alg: none` claiming ADMIN | 401 (rejected locally) |
| Catalog: forged HS256 token claiming ADMIN; expired forged token; forged token on a public route | 401, **decided by the real Authentication Service** |
| Authentication Service unreachable (real connection to a closed port) | 503, refused |

The Authentication Service's access log for the same run (log 02) shows six `verify-token` calls.
Three were sent by the check script directly and three were forwarded by the Catalog container for
the three forged-token requests. The locally rejected requests never reached it.

**Not yet run live: real ADMIN and customer tokens.** These checks need an account to log in with.
The script runs them when `CHECK_CUSTOMER_EMAIL`/`CHECK_CUSTOMER_PASSWORD` and
`CHECK_ADMIN_EMAIL`/`CHECK_ADMIN_PASSWORD` are set. They were skipped here, for two reasons:

- No credentials were available.
- The live Authentication Service has **no ADMIN user**, and creating one requires a direct change
  to its database.

Nothing was registered or changed in it to get around this. The same flows are covered by the
automated tests in §7.1.

The live expired-token check uses a token signed with a random key, so the real service refuses it
for its signature before looking at `exp`. Refusal *because of* expiry is shown by the stand-in
test in §7.1, and by the Authentication Service's own test suite (its
`DELIVERABELS/06_JWT_Authentication_Flow.md`, 27 of 27 rejected, including expired tokens).

## 8. Limitations and decisions

| Item | Note |
|---|---|
| One verification call per authenticated request | Adds latency, about one local HTTP round trip. Results are not cached, so deactivation and role changes apply at once. |
| No token revocation | Inherited from the Authentication Service: a token works until it expires unless the user is deactivated. |
| ADMIN accounts | Can only be created by a direct change to the Authentication Service's database. |
| Plain HTTP between services | Acceptable on one machine or a private Docker network. Use HTTPS if the services ever run on separate hosts. |
| python-jose | Used only for the local header pre-check, never with a secret. Known advisories (see the Task 2 audit) do not apply to that use. |

## 9. Files

| File | Change |
|---|---|
| `app/core/security.py` | Added `CUSTOMER_ROLE`, the `require_roles(*roles)` factory (`require_admin` is now built on it), and documented roles and status codes |
| `tests/test_auth_integration.py` | New: 35 end-to-end tests with a stand-in that behaves like the Authentication Service |
| `scripts/auth_integration_check.py` | New: live check against the running services, read-only |
| `README.md` | Authentication section updated |
| `DELIVERABELS/01_Project_Overview.md` | Phase 6 status |
| `DELIVERABELS/Test_Results/auth_integration_logs/` | Logs 01 (live check), 02 (Auth Service access log), 03 (pytest) |

No file in `shopease-auth-service` was changed. The only access to it was reading its code and a
read-only `SELECT role, is_active, COUNT(*)` on its user table.
