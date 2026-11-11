# 04 – API Documentation

Base URL: `http://127.0.0.1:8002`. Interactive documentation: `/docs` (Swagger UI) and `/redoc`.

**Status legend:** ✅ Implemented and tested · 🕓 Planned.

## Authentication

Every `/api/users...` endpoint needs a header with an access token from the Authentication Service:

```
Authorization: Bearer <access_token from POST http://127.0.0.1:8001/api/auth/login>
```

The User Service sends the token to the Authentication Service (`POST /api/auth/verify-token`) to be checked, and takes the caller's identity (`auth_user_id`) **only** from that response. See [06](06_JWT_Integration_Report.md).

| Failure | Status | Body |
| --- | --- | --- |
| Missing token, or not a Bearer token | 401 | `{"detail": "Could not validate credentials"}` + `WWW-Authenticate: Bearer` |
| Invalid, malformed, wrongly signed, or expired token | 401 | same |
| Account deactivated in the Authentication Service | 403 | `{"detail": "Inactive user"}` |
| Authentication Service unreachable, too slow, failing, or sending a malformed response | 503 | `{"detail": "Authentication service unavailable"}` |

## Response format

Successful responses are JSON objects, except the address list, which is a JSON array. Every error is a JSON object with `detail`:

| Status | When | Body |
| --- | --- | --- |
| 401, 403, 404, 409, 503 | See each endpoint | `{"detail": "<message>"}` |
| 422 | The request body or a path parameter fails validation | `{"detail": "Validation failed", "errors": [{"field": "phone_number", "message": "..."}]}` |
| 503 | Database unavailable | `{"detail": "Service temporarily unavailable"}` |
| 500 | Unexpected server error. No internal details are returned | `{"detail": "Internal server error"}` |

Validation errors name the field, but never repeat the submitted value. This is the same format as the Authentication Service. `field` is `body` for malformed JSON, or for a rule that covers the whole body.

## Service endpoints (no token)

| Status | Method | Path | Response |
| --- | --- | --- | --- |
| ✅ | GET | `/` | `{"service", "version", "docs_url"}` |
| ✅ | GET | `/health` | `{"status": "ok", "service", "version"}` |
| ✅ | GET | `/health/db` | `{"status": "ok", "database": "connected"}`, or 503 |

## User profile endpoints

Every endpoint acts on **the caller's own profile**, found by the `auth_user_id` from the verified token. No endpoint takes a profile ID or user ID in the path, query, or body, so no user can select another user's profile.

| Status | Method | Path | Body | Success | Errors |
| --- | --- | --- | --- | --- | --- |
| ✅ | POST | `/api/users/profile` | `UserProfileCreate` | **201** `UserProfileResponse` | 401, 403, **409**, 422, 503 |
| ✅ | GET | `/api/users/profile` | – | **200** `UserProfileResponse` | 401, 403, **404**, 503 |
| ✅ | PUT | `/api/users/profile` | `UserProfileReplace` | **200** `UserProfileResponse` | 401, 403, 404, 422, 503 |
| ✅ | PATCH | `/api/users/profile` | `UserProfileUpdate` | **200** `UserProfileResponse` | 401, 403, 404, 422, 503 |
| ✅ | DELETE | `/api/users/profile` | – | **200** `{"message": "User profile deactivated"}` | 401, 403, 404, 503 |

Profile errors:

| Status | `detail` | When |
| --- | --- | --- |
| 404 | `User profile not found` | GET, PUT, PATCH or DELETE before a profile was created |
| 409 | `User profile already exists` | POST when the caller already has an active profile, including two POSTs at the same moment |
| 403 | `User profile is deactivated` | **Any** profile operation, POST included, after deactivation (`DELETE /api/users/profile` or `PATCH /api/users/account/deactivate`) |

### POST /api/users/profile: create

```http
POST /api/users/profile
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "full_name": "Asha Rao",
  "phone_number": "+91 98765-43210",
  "date_of_birth": "1995-04-12",
  "gender": "FEMALE",
  "profile_image": "https://cdn.example.com/avatars/7.png"
}
```

**201 Created**

```json
{
  "id": 1,
  "auth_user_id": 7,
  "full_name": "Asha Rao",
  "phone_number": "+919876543210",
  "date_of_birth": "1995-04-12",
  "gender": "FEMALE",
  "profile_image": "https://cdn.example.com/avatars/7.png",
  "is_active": true,
  "created_at": "2026-11-10T09:00:00",
  "updated_at": "2026-11-10T09:00:00"
}
```

`auth_user_id` is the caller's ID from the Authentication Service. Each user can have one profile: the duplicate check is backed by the database's unique constraint on `auth_user_id`.

### GET /api/users/profile: read

Returns the caller's `UserProfileResponse` (200), or 404 if there is none yet.

### PUT /api/users/profile: full update

Replaces **every** editable field. The body has the same rules as POST: `full_name` is required, and **an omitted optional field is set to null**.

```json
{ "full_name": "Asha R.", "gender": "OTHER" }
```

After this request, `phone_number`, `date_of_birth` and `profile_image` are null. `id`, `auth_user_id`, `is_active` and `created_at` never change.

### PATCH /api/users/profile: partial update

Changes **only the fields sent**.

| Body | Effect |
| --- | --- |
| `{"phone_number": "(020) 7946-0958"}` | Phone stored as `02079460958`; everything else unchanged |
| `{"profile_image": null, "gender": null}` | Clears those two fields |
| `{"full_name": null}` | 422: `full_name cannot be null` |
| `{}` | 422: `Send at least one field to update` |

### DELETE /api/users/profile: deactivate

**200 OK**

```json
{ "message": "User profile deactivated" }
```

- Sets `is_active` to false. **The record and all its data are kept.** Nothing is deleted.
- **The Authentication Service account is not changed.** The user can still log in, and their token stays valid for other ShopEase services. This endpoint never calls the Authentication Service.
- Same effect as `PATCH /api/users/account/deactivate`, which returns a more detailed body. See the [deactivation policy](#deactivation-policy).
- Afterwards, every profile, address and account operation returns **403 `User profile is deactivated`**.
- **Recovery:** there is no self-service reactivation. Reactivation is reserved for a future admin flow (🕓), which would set `is_active` back to true. Until then it needs a database administrator.

### Request fields

`UserProfileCreate` (POST) and `UserProfileReplace` (PUT) take these fields; `UserProfileUpdate` (PATCH) takes the same fields, all optional. Leading and trailing spaces are removed from text.

| Field | Required | Rules |
| --- | --- | --- |
| `full_name` | **yes** (PATCH: optional, not null) | 1 to 255 characters after trimming. No control characters such as line breaks |
| `phone_number` | no | 7 to 15 digits after removing spaces, `-`, `(`, `)` and `.`. An optional leading `+`, or `00`, which is stored as `+`. A number starting with `+` cannot have 0 as its next digit. At most 30 characters as sent. Stored normalized |
| `date_of_birth` | no | ISO date `YYYY-MM-DD`, a real calendar date, from 1900-01-01 up to today |
| `gender` | no | Exactly one of `MALE`, `FEMALE`, `OTHER`, `PREFER_NOT_TO_SAY` (upper case) |
| `profile_image` | no | At most 500 characters, no spaces. Either an `http://` or `https://` URL with a host and no `user:password@`, or a server path starting with a single `/`, using only letters, digits, `.`, `_`, `-` and `/`, with no `..` segment, and ending in `.jpg`, `.jpeg`, `.png`, `.gif` or `.webp` |

Optional fields may be omitted or sent as `null`.

**Rejected with 422** (`Extra inputs are not permitted`): any other field, in particular `auth_user_id`, `id`, `is_active`, `email`, `password`, `created_at`. The owner always comes from the token, and credentials belong to the Authentication Service. An `auth_user_id` in the query string is ignored.

Examples of rejected values:

| Field | Value | Reason |
| --- | --- | --- |
| `full_name` | `""`, `"   "`, 256 characters, `"Asha\nRao"` | Empty, too long, control character |
| `phone_number` | `"12345"`, `"call me"`, `"+0123456789"` | Too short, not digits, `+0` |
| `date_of_birth` | tomorrow, `"1899-12-31"`, `"2001-02-30"`, `"12/04/1995"` | Future, too early, not a date, wrong format |
| `gender` | `"female"`, `"UNKNOWN"` | Not a documented choice |
| `profile_image` | `"javascript:alert(1)"`, `"ftp://…"`, `"avatar.png"`, `"/media/../x.png"`, `"/a.exe"`, `"//evil.com/a.png"`, `"https://user:pass@host/a.png"` | Unsafe scheme, not absolute, path traversal, not an image, protocol-relative, credentials in URL |

### UserProfileResponse

| Field | Type |
| --- | --- |
| `id` | int: the local profile ID (informational; no endpoint accepts it) |
| `auth_user_id` | int: the Authentication Service user ID |
| `full_name` | string |
| `phone_number`, `date_of_birth`, `gender`, `profile_image` | string or null (`date_of_birth` as `YYYY-MM-DD`) |
| `is_active` | bool: always true in a successful response, because deactivated profiles return 403 |
| `created_at`, `updated_at` | ISO date-time, UTC |

## Account management

### Which endpoint does what

| Need | Endpoint |
| --- | --- |
| Account and profile information | `GET /api/users/account` |
| Update contact information (phone) | `PATCH /api/users/account/contact` |
| Update profile details | `PUT` or `PATCH /api/users/profile` |
| All saved addresses | `GET /api/users/addresses` |
| Default delivery address | `GET /api/users/addresses/default` |
| Change the default delivery address | `PATCH /api/users/addresses/{address_id}/default` |
| Delete a saved address | `DELETE /api/users/addresses/{address_id}` |
| Deactivate the local profile | `PATCH /api/users/account/deactivate` (or `DELETE /api/users/profile`, same effect) |

### Authentication account status vs User Service profile status

A ShopEase user has **two independent statuses**, owned by two services:

| | Authentication Service account | User Service profile |
| --- | --- | --- |
| Stored in | `shopease_auth_db.users.is_active` | `shopease_user_db.user_profiles.is_active` |
| Controls | Logging in, and whether tokens are accepted anywhere in ShopEase | Access to this service's profile, address and account endpoints |
| Changed by | The Authentication Service only | `PATCH /api/users/account/deactivate` or `DELETE /api/users/profile` |
| Reported here as | `authentication_account.status` (always `ACTIVE` in a 200 response) | `profile_status`: `ACTIVE` or `NOT_CREATED` |
| When inactive | Every User Service endpoint returns **403 `Inactive user`**, before the profile is read | Every profile, address and account endpoint returns **403 `User profile is deactivated`** |

| Authentication account | User Service profile | Result in this service |
| --- | --- | --- |
| active | active | Normal access |
| active | not created | `GET /api/users/account` works (`profile_status: NOT_CREATED`). Other endpoints return 404 `User profile not found` until `POST /api/users/profile` |
| active | **deactivated** | 403 `User profile is deactivated` on every profile, address and account endpoint. The user can still log in and use other ShopEase services |
| **inactive** | any | 403 `Inactive user` everywhere. The local profile is not read or changed |

The User Service **never changes or deletes the Authentication Service account**. It makes no request to the Authentication Service other than `POST /api/auth/verify-token`, which is read-only. A test confirms deactivation makes no request at all.

### Deactivation policy

| What | What happens |
| --- | --- |
| `user_profiles` row | Kept. Only `is_active` becomes false. All fields are unchanged |
| Saved addresses | Kept, including which one is the default. Not reachable while the profile is deactivated |
| Authentication Service account | **Not changed and not deleted.** No request is sent to it |
| Afterwards | Every profile, address and account operation returns 403, including a second deactivation and `POST /api/users/profile` |
| Recovery | No self-service reactivation. Reserved for the planned admin endpoint (🕓); until then a database administrator sets `is_active` back to true, which restores the profile and addresses unchanged |

### Account endpoints

| Status | Method | Path | Body | Success | Errors |
| --- | --- | --- | --- | --- | --- |
| ✅ | GET | `/api/users/account` | – | **200** `AccountResponse` | 401, 403, 503 |
| ✅ | PATCH | `/api/users/account/contact` | `ContactUpdate` | **200** `UserProfileResponse` | 401, 403, 404, 422, 503 |
| ✅ | PATCH | `/api/users/account/deactivate` | – | **200** `AccountDeactivationResponse` | 401, 403, 404, 503 |

### GET /api/users/account

**200 OK**

```json
{
  "authentication_account": {
    "auth_user_id": 7,
    "full_name": "Asha Rao",
    "email": "asha.test@example.com",
    "role": "USER",
    "status": "ACTIVE"
  },
  "profile_status": "ACTIVE",
  "profile": { "id": 1, "auth_user_id": 7, "full_name": "Asha Rao", "...": "UserProfileResponse" }
}
```

- `authentication_account` comes from the Authentication Service's verify-token response for this request. It is not stored here.
- Before a profile is created: `"profile_status": "NOT_CREATED"` and `"profile": null` (200, not 404).
- A deactivated profile: **403 `User profile is deactivated`**.

### PATCH /api/users/account/contact

Changes the contact phone number only. `phone_number` **must be sent**; `null` clears it. Same rules as the profile phone (7 to 15 digits, stored normalized).

```json
{ "phone_number": "0091 98765 43210" }
```

Returns the updated `UserProfileResponse` (`"phone_number": "+919876543210"`).

- **The email address cannot be changed here**: it is the login identity and belongs to the Authentication Service. Sending `email` (or any other field) gives 422 `Extra inputs are not permitted`.
- An empty body gives 422 with field `phone_number`.
- No profile: 404 `User profile not found`. Deactivated: 403.

### PATCH /api/users/account/deactivate

No body. **200 OK**

```json
{
  "message": "User profile deactivated",
  "profile_status": "DEACTIVATED",
  "authentication_account_changed": false
}
```

Follows the [deactivation policy](#deactivation-policy). No profile: 404. Already deactivated: 403 `User profile is deactivated`.

## Planned admin endpoints

| Status | Method | Path | Notes |
| --- | --- | --- | --- |
| 🕓 | GET | `/api/users?skip=0&limit=50` | ADMIN role (`require_admin`). Lists profiles |
| 🕓 | GET | `/api/users/{auth_user_id}` | ADMIN role. Reads any profile. The address and account routers are registered first, so `/api/users/addresses` and `/api/users/account` never reach this route |
| 🕓 | POST | `/api/users/{auth_user_id}/reactivate` | ADMIN role. The recovery flow for deactivated profiles |

## Address endpoints

Every endpoint acts on **the caller's own addresses**. The service finds the caller's profile from the `auth_user_id` in the verified token, then looks up an address by **both** its ID and that profile's ID. The only ID a client ever sends is `address_id` in the path.

| Status | Method | Path | Body | Success | Errors |
| --- | --- | --- | --- | --- | --- |
| ✅ | POST | `/api/users/addresses` | `AddressCreate` | **201** `AddressResponse` | 401, 403, 404, 422, 503 |
| ✅ | GET | `/api/users/addresses` | – | **200** `list[AddressResponse]` | 401, 403, 404, 503 |
| ✅ | GET | `/api/users/addresses/default` | – | **200** `AddressResponse` | 401, 403, 404, 503 |
| ✅ | GET | `/api/users/addresses/{address_id}` | – | **200** `AddressResponse` | 401, 403, 404, 422, 503 |
| ✅ | PUT | `/api/users/addresses/{address_id}` | `AddressReplace` | **200** `AddressResponse` | 401, 403, 404, 422, 503 |
| ✅ | DELETE | `/api/users/addresses/{address_id}` | – | **200** `{"message": "Address deleted"}` | 401, 403, 404, 422, 503 |
| ✅ | PATCH | `/api/users/addresses/{address_id}/default` | – | **200** `AddressResponse` | 401, 403, 404, 422, 503 |

Address errors:

| Status | `detail` | When |
| --- | --- | --- |
| 404 | `User profile not found` | Any address endpoint before the caller has created a profile |
| 403 | `User profile is deactivated` | Any address endpoint after the profile is deactivated. The addresses are kept but cannot be reached |
| 404 | `Default address not found` | `GET /api/users/addresses/default` when the caller has no addresses, so no default |
| 404 | `Address not found` | No address with this ID **among the caller's addresses**: it does not exist, it was deleted, or **it belongs to another user** |
| 422 | `Validation failed`, field `address_id` | `address_id` is not a whole number from 1 to 2147483647 |

**Another user's address gives exactly the same 404 as a missing one**, with the same body, so a caller cannot find out which address IDs exist. A test compares the two responses.

### POST /api/users/addresses: add

```http
POST /api/users/addresses
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "address_type": "HOME",
  "full_name": "Asha Rao",
  "phone_number": "+91 98765-43210",
  "address_line_1": "12 MG Road",
  "address_line_2": "Flat 4B",
  "city": "Bengaluru",
  "state": "Karnataka",
  "country": "India",
  "postal_code": "560001",
  "is_default": true
}
```

**201 Created**

```json
{
  "id": 1,
  "user_id": 1,
  "address_type": "HOME",
  "full_name": "Asha Rao",
  "phone_number": "+919876543210",
  "address_line_1": "12 MG Road",
  "address_line_2": "Flat 4B",
  "city": "Bengaluru",
  "state": "Karnataka",
  "country": "India",
  "postal_code": "560001",
  "is_default": true,
  "created_at": "2026-11-11T09:00:00"
}
```

- The caller's **first address always becomes the default**, even with `"is_default": false`.
- With `"is_default": true`, the new address becomes the default and the old default is cleared in the same transaction.
- Otherwise the new address is not the default.

### GET /api/users/addresses: list

Returns a JSON array of the caller's addresses: **the default first**, then the others from oldest to newest. A profile with no addresses gives `[]`.

### GET /api/users/addresses/default: default delivery address

Returns the caller's default `AddressResponse`. While the caller has at least one address there is always exactly one default, so this returns 404 `Default address not found` only when they have no addresses. Other services (for example Checkout) can use it with the customer's token.

`default` is a fixed path, not an address ID: the route is declared before `/{address_id}`.

### GET /api/users/addresses/{address_id}: read

Returns one `AddressResponse`, or 404 `Address not found`.

### PUT /api/users/addresses/{address_id}: full update

Replaces **every** editable field. The body has the same rules as POST, without `is_default`.

- An omitted `address_line_2` is set to null, and an omitted `address_type` to `HOME`.
- `is_default` is **not accepted** here (422). The address keeps its current default status. To change it, use `PATCH .../default`.
- `id`, `user_id` and `created_at` never change.

### DELETE /api/users/addresses/{address_id}: delete

**200 OK** `{"message": "Address deleted"}`. The address row is permanently deleted.

- If it was the default, **the oldest remaining address (lowest `id`) automatically becomes the default** in the same transaction. This is deliberate, implemented, and tested: the deleted address can never be left as a stale default, and a user with addresses always has one default for checkout. To choose a different one, call `PATCH .../default` afterwards.
- Deleting the last address leaves no default. The next address added becomes the default.
- The profile is not affected.

### PATCH /api/users/addresses/{address_id}/default: set default

Takes no body. **200 OK** with the address, now `"is_default": true`. The previous default is cleared in the same transaction. Calling it on the current default changes nothing and also returns 200.

### Request fields

`AddressCreate` (POST) and `AddressReplace` (PUT) take these fields. Leading and trailing spaces are removed from text.

| Field | Required | Rules |
| --- | --- | --- |
| `address_type` | no, default `HOME` | Exactly one of `HOME`, `OFFICE`, `OTHER` (upper case). Not null |
| `full_name` | **yes** | The recipient's name. 1 to 255 characters after trimming, no control characters |
| `phone_number` | **yes** | The recipient's phone. Same rule as the profile phone: 7 to 15 digits, stored normalized |
| `address_line_1` | **yes** | 1 to 255 characters, no control characters such as line breaks |
| `address_line_2` | no | Same rule as `address_line_1`, or null. An empty string is rejected; send null or leave it out |
| `city`, `state`, `country` | **yes** | 1 to 100 characters each, no control characters |
| `postal_code` | **yes** | 3 to 20 characters: letters, digits, spaces and `-`, starting and ending with a letter or digit. Sent as a string (`"560001"`), not a number |
| `is_default` | no, POST only | `true` or `false`, default `false` |

**Rejected with 422** (`Extra inputs are not permitted`): any other field, in particular `user_id`, `auth_user_id`, `id`, `created_at`, `default_marker`, and `is_default` on PUT. A `user_id` or `auth_user_id` in the query string is ignored.

Examples of rejected values:

| Field | Value | Reason |
| --- | --- | --- |
| `address_type` | `"WORK"`, `"home"`, `"Office"`, `null` | Not a documented choice (exact upper case) |
| `full_name`, `address_line_1`, `city`, `state`, `country` | `""`, `"   "`, too long, `"12 MG Road\r\nInjected"` | Empty, too long, control character |
| `phone_number` | `"12345"`, `"not a phone"`, `null` | Too short, not digits, missing |
| `postal_code` | `"56"`, `"560 001!"`, `"-560001"`, 21 characters, `560001` (a number) | Too short, invalid character, bad start, too long, not a string |

### AddressResponse

| Field | Type |
| --- | --- |
| `id` | int: the address ID, used in the paths above |
| `user_id` | int: the local profile ID that owns the address (not the Authentication Service ID) |
| `address_type` | `HOME`, `OFFICE` or `OTHER` |
| `full_name`, `phone_number`, `address_line_1`, `city`, `state`, `country`, `postal_code` | string. The phone number is normalized |
| `address_line_2` | string or null |
| `is_default` | bool |
| `created_at` | ISO date-time, UTC |

### Default-address rules and transactions

1. A user has **at most one default address**, and exactly one while they have any address.
2. Setting a new default (POST with `is_default: true`, or `PATCH .../default`) clears the previous default first, then sets the new one.
3. **Every address write runs in one database transaction.** If any step fails, everything is rolled back, so the old default is never lost and no half-finished change is saved. The caller gets `503 Service temporarily unavailable`.
4. **Every write (POST, PUT, DELETE, PATCH) first locks the owning profile row** with `SELECT ... FOR UPDATE`. Concurrent writes for the same user run one after another, and each sees the previous one's result. Different users never block each other.
5. **The database enforces the rule as well:** the unique key `uq_user_addresses_one_default_per_user` rejects a second default even if the application code were wrong. See [05](05_Database_Schema.md).
