"""Authentication through the ShopEase Authentication Service.

The Catalog Service never decodes or trusts a JWT itself, and holds no JWT secret. For each
protected request it forwards the caller's bearer token to the Authentication Service's
own endpoint (shopease-auth-service, POST /api/auth/verify-token):

    POST {AUTH_SERVICE_VERIFY_URL}        Authorization: Bearer <token>, no body
    200 {"valid": true, "user": {"id": int, "full_name": str, "email": str,
                                 "role": str, "is_active": bool}}
    401 {"detail": "Could not validate credentials"}
    403 {"detail": "Inactive user"}
    500 / 503                              failure inside the Authentication Service

Only a 200 response with that exact shape authenticates a caller. Everything else fails
closed. The token is never logged, stored, or included in a response.

Before that call, a local pre-check (python-jose, no secret) rejects anything that is not a
well-formed JWT signed with JWT_ALGORITHM, the algorithm the Authentication Service uses.
The pre-check can only reject a token, never accept one: its claims are not trusted.

Roles. The Authentication Service stores a free-text role per user. It defines two values:
"USER", the default for every registered account (the shop's customers; migration 12ee6f689116
renamed the older "customer" value to "USER"), and "ADMIN", set directly in its database. It has
no "CUSTOMER" role. Roles are compared exactly, so "admin" is not ADMIN. The role used is the one
verify-token returns from the user's database record, never the token's own "role" claim, so a
demoted admin loses access at once.

Access rules used by the routers:
  - Browsing active categories and products: anyone, including customers (USER), with or
    without a token.
  - Seeing inactive records, and every write or inventory operation: ADMIN role.

Status codes:
  401  no token, wrong scheme, malformed, expired, wrongly signed, or unknown user
  403  valid token, but the user is inactive or lacks the required role
  503  the Authentication Service could not give an answer (down, timeout, error, bad reply).
       The request is refused (fail closed). Anonymous browsing does not call the
       Authentication Service and keeps working.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# The two role values of shopease-auth-service (see the module docstring).
ADMIN_ROLE = "ADMIN"
CUSTOMER_ROLE = "USER"

# Signed 32-bit INT, the type of every ID column in this service and in the Authentication Service.
MAX_DB_INT = 2_147_483_647

# A real token is a few hundred bytes. Anything far larger is rejected without a network call.
MAX_TOKEN_LENGTH = 4096

# auto_error=False: a missing token, or another scheme such as Basic, gets this service's own 401.
bearer_scheme = HTTPBearer(auto_error=False, description="Access token from the ShopEase Authentication Service")


def _to_database_id(value: Any) -> int:
    """Convert the verified user ID to the database integer type, rejecting anything ambiguous."""
    # bool is a subclass of int, and true must not become user 1.
    if isinstance(value, bool):
        raise ValueError("user id must be an integer")
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    if not isinstance(value, int):
        raise ValueError("user id must be an integer")
    return value


DatabaseId = Annotated[int, BeforeValidator(_to_database_id), Field(ge=1, le=MAX_DB_INT)]


class _VerifiedUser(BaseModel):
    # Extra fields are ignored, so the Authentication Service may add fields without breaking this.
    model_config = ConfigDict(extra="ignore")

    id: DatabaseId
    full_name: str
    email: str
    role: str = Field(min_length=1)
    is_active: bool


class _VerifyTokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    valid: bool
    user: _VerifiedUser


@dataclass(frozen=True)
class AuthenticatedUser:
    """The caller, as confirmed by the Authentication Service for this request."""

    auth_user_id: int
    full_name: str
    email: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == ADMIN_ROLE


@lru_cache
def get_auth_client() -> httpx.Client:
    """Dependency: one shared HTTP client, so connections to the Authentication Service are reused.

    Redirects are not followed, so the token is never sent to any other address.
    """
    return httpx.Client(timeout=get_settings().auth_service_timeout_seconds, follow_redirects=False)


def _unauthenticated() -> HTTPException:
    # Same response as the Authentication Service, so callers cannot learn why a token was rejected.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _inactive_user() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")


def _role_required(roles: frozenset[str]) -> HTTPException:
    if roles == {ADMIN_ROLE}:
        detail = "Admin role required"
    else:
        detail = "One of these roles is required: " + ", ".join(sorted(roles))
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _admin_required() -> HTTPException:
    return _role_required(frozenset({ADMIN_ROLE}))


def _auth_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Authentication service unavailable",
    )


def has_expected_format(token: str) -> bool:
    """True if the token is a well-formed JWT whose header names the configured algorithm.

    The signature is NOT checked here; only the Authentication Service can do that. This only
    spares a network call for tokens that could never be valid, such as alg "none" or garbage.
    """
    try:
        header = jwt.get_unverified_header(token)
    except (JWTError, ValueError, TypeError):
        return False
    return header.get("alg") == get_settings().jwt_algorithm


def verify_access_token(token: str, client: httpx.Client) -> AuthenticatedUser:
    """Ask the Authentication Service whether the token is valid. Raise HTTPException if not."""
    if not token or len(token) > MAX_TOKEN_LENGTH or not has_expected_format(token):
        raise _unauthenticated()

    try:
        response = client.post(
            str(get_settings().auth_service_verify_url),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        # Class name only: the request, and so the token, must not reach the logs.
        logger.error("Authentication service request failed: %s", type(exc).__name__)
        raise _auth_unavailable() from exc

    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        raise _unauthenticated()
    if response.status_code == status.HTTP_403_FORBIDDEN:
        raise _inactive_user()
    if response.status_code != status.HTTP_200_OK:
        # Covers 5xx, and also 3xx/404, which point to a wrong AUTH_SERVICE_VERIFY_URL.
        logger.error("Authentication service returned status %s", response.status_code)
        raise _auth_unavailable()

    try:
        result = _VerifyTokenResponse.model_validate_json(response.content)
    except ValidationError as exc:
        # Neither the body nor the validation details are logged: they hold user data.
        logger.error("Authentication service returned a malformed verification response")
        raise _auth_unavailable() from exc

    # The Authentication Service never sends these with 200; if it ever does, fail closed.
    if result.valid is not True:
        raise _unauthenticated()
    if not result.user.is_active:
        raise _inactive_user()

    user = result.user
    return AuthenticatedUser(
        auth_user_id=user.id, full_name=user.full_name, email=user.email, role=user.role
    )


def get_current_authenticated_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    client: httpx.Client = Depends(get_auth_client),
) -> AuthenticatedUser:
    """Dependency for protected routes: the caller confirmed by the Authentication Service."""
    if credentials is None:
        raise _unauthenticated()
    return verify_access_token(credentials.credentials, client)


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    client: httpx.Client = Depends(get_auth_client),
) -> AuthenticatedUser | None:
    """Dependency for public routes: None without a token, otherwise the verified caller.

    A token that is sent but invalid is still rejected with 401; it is never silently ignored.
    """
    if credentials is None:
        return None
    return verify_access_token(credentials.credentials, client)


def require_roles(*roles: str) -> Callable[..., AuthenticatedUser]:
    """Build a dependency that allows only verified callers with one of these roles.

        @router.post(..., dependencies=[Depends(require_roles(ADMIN_ROLE))])

    No token or an invalid one gives 401, a valid token with another role gives 403.
    """
    allowed = frozenset(roles)
    if not allowed or not all(isinstance(role, str) and role for role in allowed):
        raise ValueError("require_roles needs at least one non-empty role name")

    def role_dependency(
        user: AuthenticatedUser = Depends(get_current_authenticated_user),
    ) -> AuthenticatedUser:
        if user.role not in allowed:
            raise _role_required(allowed)
        return user

    return role_dependency


# Every write and inventory operation. Defined once so that routers and test overrides share it.
require_admin = require_roles(ADMIN_ROLE)
require_admin.__doc__ = "Dependency: allow only callers whose current role in the Authentication Service is ADMIN."


def ensure_admin_for_inactive(include_inactive: bool, user: AuthenticatedUser | None) -> None:
    """Public listings show inactive records only to an admin."""
    if not include_inactive:
        return
    if user is None:
        raise _unauthenticated()
    if not user.is_admin:
        raise _admin_required()
