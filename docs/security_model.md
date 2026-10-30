# Authentication and Trust Model

How ShopEase decides **who** is calling and **what** they may do. This describes what is
implemented as of 2026-10-30; the design was accepted by the project owner the same day (ADR-16). It has **not had an independent security review** and is not
claimed to be production-grade (see *Known limitations*).

Related: ADR-05, ADR-08, ADR-16 in [implementation_decisions.md](implementation_decisions.md) ·
contracts in [rest_api_notes.md](rest_api_notes.md).

---

## 1. Tokens

| Token | Issued by | Format | Lifetime | Audience (`aud`) | Used for |
|-------|-----------|--------|----------|------------------|----------|
| Access token | `POST /api/auth/login`, `/refresh` | JWT, RS256 | 15 min (`JWT_ACCESS_TOKEN_MINUTES`) | `shopease-api` | End-user requests (`Authorization: Bearer`) |
| Refresh token | same | 256-bit random, opaque | 14 days (`REFRESH_TOKEN_DAYS`) | — | Getting a new access token; stored only as SHA-256 |
| Service token | `POST /internal/auth/service-token` | JWT, RS256 | 5 min (`JWT_SERVICE_TOKEN_MINUTES`) | `shopease-internal` | Service-to-service calls on `/internal/*` |

Access token claims: `iss`, `aud`, `sub` (user UUID), `role` (`customer`/`admin`),
`token_use=access`, `iat`, `nbf`, `exp`, `jti`; header `kid`.
Service token claims: `sub=svc:<name>`, `scope` (space-separated), `token_use=service`,
plus the same registered claims.

**Verification** (`shared/shopease_shared/security.py`, used by the gateway and every
service) accepts a token only if all of these hold:
- header `alg` is exactly `RS256` (`none`, HS256 and others are rejected), and `kid` names a
  known key;
- the signature verifies against auth_service's public key from the JWKS;
- `iss`, `aud`, `exp`, `iat`, `sub`, `jti` are present; issuer and audience match; not
  expired (30 s leeway);
- `token_use` matches the route: an access token can't be used on `/internal/*`, and a
  service token can't be used on public routes; an access token's `sub` must be a UUID.

Failures return `401` with `WWW-Authenticate: Bearer` and code `UNAUTHENTICATED` (no
token), `TOKEN_EXPIRED` or `INVALID_TOKEN`. The token itself is never logged.

**Keys.** Only auth_service holds the RSA private key (`JWT_PRIVATE_KEY_PATH`, generated with
`scripts/generate_jwt_key.py`, git-ignored). The public key is published at
`GET /api/auth/.well-known/jwks.json`. Other components fetch it once and cache it
(`JWKS_CACHE_SECONDS`, default 300); an unknown `kid` triggers one refetch, which allows
rotation. If the JWKS can't be fetched and nothing is cached, requests get
`503 AUTH_UNAVAILABLE`: verification fails closed. Without a configured key, development
and test runs use a temporary key; any other `APP_ENV` refuses to start.

## 2. Where each check happens

```
Client ──HTTPS──► API Gateway ──────────────► Service ───────────────► its own database
                  1. rate limit per IP        3. verify token again     (own credentials only)
                  2. verify access token      4. authorize: role,
                     (protected routes)          scope, ownership
                  strips X-User-Token
                  never routes /internal/*
```

| Layer | Authenticates | Authorizes | Why both |
|-------|---------------|------------|----------|
| Gateway | Yes, on every non-public route | **No** | Rejects junk early and keeps it off the services |
| Each service | Yes, again, on every protected route | **Yes**: role, scope, resource ownership | The gateway can be bypassed (internal network, misconfiguration, SSRF); the internal network is not trusted |

Public routes (no token): `POST /api/auth/register|login|refresh`, the JWKS,
`GET /api/products[/{id}]`, `GET /api/categories`, `POST /api/payments/webhooks/{provider}`
(the provider's signature is checked by payment_service). The table is in
`api_gateway/app/edge.py`.

## 3. Identity is never taken from plain headers

- User identity is **only** the `sub` of a verified access token. Headers such as
  `X-User-Id` are ignored, and user_service tests prove that sending them changes nothing.
- The gateway **removes** any `X-User-Token` header a client sends.
- Request bodies can't set identity: profile updates reject unknown fields (`user_id`
  included) with `422`.

## 4. Service-to-service trust (ADR-08)

1. An operator registers each calling service once:
   `python scripts/auth_cli.py create-service-client svc:order --scope addresses:read --scope products:read`.
   The secret is printed once and stored only in that service's environment; auth_db keeps
   an Argon2id hash.
2. The calling service exchanges `client_id` + `client_secret` at
   `POST /internal/auth/service-token` (optionally asking for a subset of its scopes) and
   caches the 5-minute token.
3. It calls the internal endpoint with `Authorization: Bearer <service token>`. When acting
   for a user, it also sends that user's access token in **`X-User-Token`**.
4. The receiving service verifies the service token (audience `shopease-internal`), checks
   the required **scope**, verifies `X-User-Token` like any access token, and checks that the
   resource belongs to that user.

Example: `GET /internal/users/{user_id}/addresses/{address_id}` needs scope
`addresses:read`, and an `X-User-Token` whose `sub` equals `user_id`. Otherwise it returns
`401`, `403 INSUFFICIENT_SCOPE` or `404`. A compromised service token alone can't read
arbitrary users' addresses.

Scopes defined so far: `products:read`, `inventory:reserve`, `addresses:read`, `orders:read`,
`orders:payment`.

## 5. Accounts and sessions

| Rule | Implementation |
|------|----------------|
| Password storage | Argon2id (argon2-cffi, RFC 9106 defaults), rehashed on login when parameters change. Never returned, never logged |
| Password policy | 12–128 characters; a new password must differ from the current one |
| Email | Lower-cased before storage; unique |
| Login errors | Unknown email and wrong password both give `401 INVALID_CREDENTIALS`; an unknown email still runs a dummy hash so timing is similar |
| Lockout | `MAX_FAILED_LOGINS` (5) failures lock the account for `LOCKOUT_MINUTES` (15): `423 ACCOUNT_LOCKED` + `Retry-After`, even with the right password |
| Refresh | One-time use: each refresh rotates the token. Presenting an already-rotated token revokes **every** session of that user (theft detection) |
| Logout | `POST /api/auth/logout` revokes the given refresh token (only if it is the caller's), or all of the caller's sessions when no token is sent |
| Password change | `PUT /api/auth/password` needs the current password and revokes all refresh tokens |
| Roles | `customer` by default. `PATCH /api/auth/users/{id}/role` is admin-only; the first admin is created with `python scripts/auth_cli.py promote-admin <email>` |
| Current user | `GET /api/users/me` (user_service). auth_service has no separate "me" route in the approved design |

## 6. User data access rules (user_service)

- `/api/users/me...` always acts on the token's `sub`; there is no user ID in those paths.
- Address reads, updates and deletes filter by **both** `address_id` and the caller's
  `user_id`. Someone else's address answers `404 ADDRESS_NOT_FOUND`, the same as a missing
  one, so IDs can't be probed.
- `GET /api/users/{user_id}` is the only cross-user read and requires `role=admin` (`403`
  otherwise), checked in user_service.
- user_service never connects to auth_db; profiles are created on first access (ADR-09).

## 7. Rate limiting

The gateway limits requests per client IP over a fixed 60-second window:
`RATE_LIMIT_AUTH_PER_MINUTE` (default 20) for `POST /api/auth/register|login|refresh`, and
`RATE_LIMIT_DEFAULT_PER_MINUTE` (default 0 = off) for everything else. Over the limit:
`429 RATE_LIMITED` with `Retry-After`; responses carry `RateLimit-Limit/Remaining/Reset`. The
client address is the TCP peer: `X-Forwarded-For` is not trusted.

## 8. Logging

Logs carry request IDs, user IDs, client IDs and outcomes. They never carry passwords,
password hashes, access/refresh/service tokens, client secrets or email addresses.
Validation errors don't echo input. A test checks this for the auth flows, and the
end-to-end check scanned every log line of a full session (see the Day 2 report).

## 9. Known limitations (to address before production)

- **No independent security review or penetration test has been done.**
- Access tokens can't be revoked before they expire (15 min). Logout, password change and role
  changes apply to new tokens only. A `token_revocations` (jti) table is the documented option.
- Rate limits and lockout counters: the rate limiter is in-memory per gateway process
  (needs a shared store such as Redis with several gateways). Account lockout lets an
  attacker lock a victim's account for 15 minutes, and the `423` reveals that the email exists.
- Registration answers `409` for an existing email, which reveals registered emails. Kept
  deliberately (accepted 2026-10-30): a neutral response only helps together with email
  verification, which is out of scope. Login stays non-enumerating, and the gateway
  rate-limits registration per IP.
- No TLS inside the stack (development); TLS terminates in front of the gateway in production.
- Key rotation: verifiers refetch on an unknown `kid`, but auth_service publishes one key at a
  time. Publishing old and new keys together during rotation still has to be built.
- Service-client secrets have no expiry; rotate them with `create-service-client --rotate`.
- No MFA, email verification or password-reset flow.
- Dependency scanning (e.g. `pip-audit`) is not wired into a pipeline yet.
