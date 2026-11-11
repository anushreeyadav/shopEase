# 06 – JWT Integration Report

How the User Service authenticates requests with access tokens issued by the existing ShopEase Authentication Service. It does this without its own login, registration, or JWT code, and without the JWT secret.

## 1. What the Authentication Service actually does

Inspected on 10 November 2026 in `shopease-auth-service` (source last changed 5 November 2026). Nothing in that service was modified.

### Token generation: `app/core/security.py`, `create_access_token()`

```python
claims = {"sub": str(user_id), "role": role, "iat": issued_at, "exp": issued_at + expires_delta}
return jwt.encode(claims, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm)
```

| Item | Value | Source |
| --- | --- | --- |
| Library | python-jose | `requirements.txt` |
| Algorithm | `JWT_ALGORITHM`, default **HS256** (HMAC only: HS256, HS384 or HS512) | `app/core/config.py` |
| Key | `JWT_SECRET_KEY`, a shared HMAC secret of at least 32 characters | `app/core/config.py` |
| Lifetime | `ACCESS_TOKEN_EXPIRE_MINUTES`, default **30** (1 to 1440) | `app/core/config.py` |
| `sub` | User ID as a **decimal string**, for example `"7"` | `create_access_token` |
| `role` | Role when the token was issued, for example `"USER"` | `create_access_token` |
| `iat`, `exp` | Issued-at and expiry, UTC | `create_access_token` |

### Token checking: `decode_access_token()` and `get_current_user()`

1. Only the configured algorithm is accepted, and `sub`, `exp` and `iat` are required.
2. `sub` must be ASCII digits, and `role` must be a non-empty string.
3. The user is loaded from the auth database on every call. A user that no longer exists gets 401, and an inactive user gets 403.
4. Every token failure gives the same 401, `Could not validate credentials`, with `WWW-Authenticate: Bearer`.

### Verify endpoint: `app/routers/auth_routes.py`, `verify_token()`

```python
@router.post("/verify-token", response_model=TokenVerificationResponse, ...)
def verify_token(user: User = Depends(get_current_user)):
    return {"valid": True, "user": user}
```

The URL is `POST /api/auth/verify-token`: `api_prefix` `/api` + router prefix `/auth`. The request has no body; the token goes in `Authorization: Bearer <token>`.

### Response schema: `app/schemas/auth_schema.py`

```python
class TokenVerificationResponse(BaseModel):   valid: bool;  user: UserResponse
class UserResponse(BaseModel):                id: int;  full_name: str;  email: str;  role: str;  is_active: bool
```

| Status | Body | When |
| --- | --- | --- |
| 200 | `{"valid": true, "user": {"id": 7, "full_name": "...", "email": "...", "role": "USER", "is_active": true}}` | Token valid, user exists and is active. `role` is the current role from the database |
| 401 | `{"detail": "Could not validate credentials"}` | No token, wrong scheme, malformed, wrong signature, expired, bad claims, or user deleted |
| 403 | `{"detail": "Inactive user"}` | User deactivated |
| 503 | `{"detail": "Service temporarily unavailable"}` | Auth database error (`exception_handlers.py`) |
| 500 | `{"detail": "Internal server error"}` | Any other failure (`exception_handlers.py`) |

The auth service never returns `"valid": false`. Its documentation says that any status other than 200 means "not verified". `users.id` is a signed 32-bit `INT`, the same type as `user_profiles.auth_user_id` here.

## 2. How the User Service verifies a token

Code: [`app/core/security.py`](../app/core/security.py).

```
Client                         User Service (8002)                       Authentication Service (8001)
  | GET /api/users/profile        |                                                  |
  | Authorization: Bearer eyJ...  |                                                  |
  |------------------------------>| 1. HTTPBearer reads the header                   |
  |                               |    none / not Bearer / empty / > 4096 chars: 401 |
  |                               | 2. POST AUTH_SERVICE_VERIFY_URL                  |
  |                               |    Authorization: Bearer eyJ...  (no body)       |
  |                               |------------------------------------------------->| 3. checks signature, algorithm,
  |                               |                                                  |    exp/iat/sub, loads the user,
  |                               |<-------------------------------------------------|    checks is_active
  |                               | 4. maps the response (table below)               |
  |                               | 5. validates the 200 body, converts user.id      |
  |                               |    to the database INT type                      |
  |                               | 6. route receives AuthenticatedUser(auth_user_id,|
  |                               |    full_name, email, role)                       |
  |<------------------------------| response for user auth_user_id only              |
```

### Reusable dependency

```python
from app.core.security import AuthenticatedUser, get_current_authenticated_user, require_admin

@router.get("/me")
def read_profile(user: AuthenticatedUser = Depends(get_current_authenticated_user)): ...

@router.get("/")
def list_profiles(admin: AuthenticatedUser = Depends(require_admin)): ...   # role == "ADMIN"
```

### Response mapping (fail closed)

| Situation | Authentication Service | User Service returns |
| --- | --- | --- |
| Valid token, active user | 200, valid body | **Continues** with `AuthenticatedUser` |
| No `Authorization` header, empty token, non-Bearer scheme, token over 4096 characters | *not called* | **401** `Could not validate credentials` + `WWW-Authenticate: Bearer` |
| Invalid, malformed, wrongly signed, or **expired** token, or user deleted | 401 | **401** (same body and header) |
| 200 with `"valid": false` (never sent today) | 200 | **401** |
| **Inactive** auth user | 403 | **403** `Inactive user` |
| 200 with `"is_active": false` (never sent today) | 200 | **403** `Inactive user` |
| **Malformed verification response**: not JSON, missing fields, wrong types, bad user ID | 200 | **503** `Authentication service unavailable` |
| Auth service error or misconfigured URL: 5xx, 404, any 3xx | any other | **503** |
| Timeout, connection refused, DNS failure, protocol error | *no response* | **503** |

The User Service passes the caller on **only** after a 200 response that passes every check. There is no fallback that decodes the token locally, and no cache of earlier results.

**Why an inactive user gets 403, not 401:** the token is genuine but the account is disabled. This matches the Authentication Service's own response, so clients see the same status from both services.

**Why a malformed response gives 503, not 401:** the fault is in the Authentication Service or its configuration, not in the caller's token. A 401 would make clients discard a token that may be valid. Either way, access is refused.

### Converting the user ID to the database type

`user.id` must become an `int` between 1 and 2,147,483,647, the range of the `INT` column.

| Received `id` | Result |
| --- | --- |
| `7` | `7` |
| `"7"` (ASCII digits) | `7` |
| `true`, `7.5`, `"7a"`, `"٣"` (non-ASCII digit), `null`, `0`, `-7`, `2147483648` | rejected as malformed: 503 |

`true` is rejected explicitly, because in Python `bool` is a subclass of `int`, and `true` would otherwise become user 1.

### Security properties

| Rule | How it is enforced |
| --- | --- |
| Never trust an unverified token | Only a validated 200 response authenticates. Every other path raises 401, 403 or 503 |
| Identity never comes from the client | `auth_user_id` is taken only from the verify response. Request schemas use `extra="forbid"`, so a body with `auth_user_id` is rejected with 422. Tests send `auth_user_id` in the query, body and `X-User-Id` headers and confirm they are ignored |
| No JWT secret in the User Service | No `JWT_*` setting, no JWT library in `requirements.txt`. A test fails if a JWT or secret setting is added |
| Timeouts | `AUTH_SERVICE_TIMEOUT_SECONDS` (default 5, at most 30) applies to connecting, reading, writing, and waiting for a pooled connection |
| Token goes nowhere else | The token is sent only to `AUTH_SERVICE_VERIFY_URL`. Redirects are not followed, so a 3xx cannot pass it to another host |
| Token never logged or returned | Failures are logged as the exception class or status code only. Tests capture DEBUG logs, including HTTPX's own, and check that no log line and no response contains the token |
| Up-to-date role and status | `role` and `is_active` come from the auth database on every request, so a role change or deactivation takes effect at once, not when the token expires |

## 3. Configuration and connectivity

| Variable | Default | Purpose |
| --- | --- | --- |
| `AUTH_SERVICE_VERIFY_URL` | `http://127.0.0.1:8001/api/auth/verify-token` | Verify endpoint, as reached by this service |
| `AUTH_SERVICE_TIMEOUT_SECONDS` | `5` | Timeout per call, more than 0 and at most 30 |
| `DOCKER_AUTH_SERVICE_VERIFY_URL` | `http://host.docker.internal:8001/api/auth/verify-token` | Used by `docker-compose.yml` as `AUTH_SERVICE_VERIFY_URL` inside the container |

| User Service runs | Authentication Service runs | `AUTH_SERVICE_VERIFY_URL` |
| --- | --- | --- |
| uvicorn on this machine | uvicorn on this machine, port 8001 | `http://127.0.0.1:8001/api/auth/verify-token` (default) |
| uvicorn on this machine | its Docker stack (publishes `127.0.0.1:8001`) | `http://127.0.0.1:8001/api/auth/verify-token` (default) |
| its Docker stack | its Docker stack, or uvicorn, on this machine | `http://host.docker.internal:8001/api/auth/verify-token`. Compose sets this from `DOCKER_AUTH_SERVICE_VERIFY_URL`, and `extra_hosts: host.docker.internal:host-gateway` makes the name work on Linux as well as Docker Desktop |
| a shared Docker network (future platform compose) | same network | `http://<auth container name>:8001/api/auth/verify-token` |

The URL must point at the verify endpoint itself. A wrong path gives 404, and a wrong scheme or host gives a redirect or a connection error. All of these return 503 from the User Service, and the log line shows the status code or error class.

Quick connectivity check without a token (expect `401`, which proves the endpoint is reachable):

```powershell
curl.exe -s -o NUL -w "%{http_code}" -X POST http://127.0.0.1:8001/api/auth/verify-token
```

## 4. Why the JWT secret is not shared

| Option | Chosen? | Reason |
| --- | --- | --- |
| Call `POST /api/auth/verify-token` for each request | **Yes** | No signing key outside the Authentication Service, so this service cannot forge tokens. Deleted or deactivated users are rejected at once. Token rules stay in one place |
| Verify the signature locally with a shared HS256 secret | No | HS256 uses one key for signing and verifying, so every holder could create tokens for any user. It also cannot see deactivation before expiry. It would need a separately reviewed design, for example asymmetric keys (RS256/EdDSA) with a published public key |

**Trade-off:** each protected request makes one extra HTTP call, and protected endpoints return 503 while the Authentication Service is down. The health endpoints keep working. Caching verify results briefly would reduce the load, but delay deactivation, so it is not done.

## 5. Automated tests

File: [`tests/test_auth_integration.py`](../tests/test_auth_integration.py), 57 tests. The Authentication Service is replaced by `httpx.MockTransport`, which returns the real response bodies listed in section 1. Requests go through a test app over HTTP, so bearer parsing, status codes and headers are tested as a client sees them.

| Area | What is tested |
| --- | --- |
| Valid token | 200, `auth_user_id` = 7. The request is `POST` to the configured URL with the unchanged `Authorization` header and no body. A lowercase `bearer` scheme is accepted. Extra response fields are tolerated |
| ID conversion | `42` and `"42"` become the int 42, and the maximum `INT` value is accepted |
| Identity spoofing | `auth_user_id` in the query, body and `X-User-Id`/`X-Auth-User-Id` headers is ignored |
| Missing token (401, auth service not called) | No header, empty header, `Bearer` with no token, `Basic` scheme, no scheme, a token over 4096 characters |
| Invalid or expired token (401) | Auth service 401 for an invalid signature, an expired token, a malformed token, and a deleted user. `valid: false` |
| Inactive user (403) | Auth service 403, and `is_active: false` in a 200 response |
| Malformed response (503) | 16 bodies: missing `user` or `valid`, wrong shape, array, null, `id` of `true`, 0, −7, too large, 7.5, `"7a"`, non-ASCII digit, null; empty role; bad `is_active`; null email; and a non-JSON body |
| Unavailable (503) | Auth service 503, 500, 404, 502, a redirect (not followed), connection error, connect timeout, read timeout, protocol error. The configured timeout and `follow_redirects=False` are applied |
| No leaks | For 6 outcomes, the token appears in no log line (DEBUG level, HTTPX logs included), response body, or header |
| Roles | `require_admin` gives 403 for USER and 200 for ADMIN |

Result on 10 November 2026: `pytest` **81 passed**: 57 integration tests plus 24 other tests. In the final run on 11 November 2026, the same 57 tests passed within the full suite (518 passed on SQLite and on MySQL). The security audit adds 150 tests that go through the real verification path with signed tokens ([07](07_API_Testing_Report.md)).

## 6. Live test against the running Authentication Service

Run on 11 November 2026 (Day 2). Setup:
- The Authentication Service was started from its own folder, with its files unchanged (`docker compose up -d --build --wait`), on `127.0.0.1:8001`.
- The User Service ran in its Docker container on `127.0.0.1:8002`. It reached the Authentication Service at `http://host.docker.internal:8001/api/auth/verify-token`.
- Test users were registered and logged in, and every call used their real access tokens. Tokens are shown here only as `eyJhbGciOi…`.

| # | Scenario | Expected | Actual | Pass |
| --- | --- | --- | --- | --- |
| 1 | Log in on the Authentication Service | 200 + access_token | 200, `eyJhbGciOi…` (redacted) | ✅ |
| 2 | Protected User Service endpoint with that token | 200 (or 404 if there is no profile yet) | `GET /api/users/account` 200, `auth_user_id` equal to the logged-in user. `GET /api/users/profile` before creation: 404 | ✅ |
| 3 | No Authorization header | 401 | 401 `Could not validate credentials` | ✅ |
| 4 | Token with its signature changed | 401 | 401 (rejected by the Authentication Service) | ✅ |
| 4b | Malformed token (`Bearer not-a-jwt`), and the `Basic` scheme | 401 | 401 and 401 | ✅ |
| 5 | Expired token | 401 | **Not run live.** It needs a 30-minute wait, or a shorter expiry setting on the Authentication Service, which was not to be modified. Covered by automated tests with the stand-in (section 5, and test case 3 in [07](07_API_Testing_Report.md)) | – |
| 6 | Token of a user whose **Authentication Service** account is inactive | 403 | **Not run live.** It needs the account deactivated inside the Authentication Service. Covered by automated tests with the stand-in | – |
| 6b | Token of a user whose **User Service profile** was deactivated | 403 on profile, address and account endpoints; token still valid at the Authentication Service | 403 `User profile is deactivated` on all 7 calls tried; `verify-token` 200 `is_active: true`; login still 200 | ✅ |
| 7 | Authentication Service stopped | 503 | 503 `Authentication service unavailable`; 200 again after it restarted | ✅ |
| 8 | USER token on an ADMIN endpoint | 403 | **Not applicable:** admin endpoints are not implemented (`GET /api/users/{id}` gives 404 Not Found) | – |
| 9 | ADMIN token on an ADMIN endpoint | 200 | **Not applicable**, as above | – |
| 10 | Token in logs | Not present | Neither the user-service log nor the auth-service log contains any of the 3 tokens used, whole or by their signature | ✅ |

Evidence:
- [`Test_Results/docker_auth_token_verification.txt`](Test_Results/docker_auth_token_verification.txt): rows 1–4, 7 and 10.
- [`Test_Results/final_live_api_audit.txt`](Test_Results/final_live_api_audit.txt): rows 2–4b, 6b and 8.
- [`Test_Results/final_validation_checks.txt`](Test_Results/final_validation_checks.txt): the log search.
