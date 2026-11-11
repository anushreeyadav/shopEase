"""Authentication through the ShopEase Authentication Service.

The User Service never decodes or trusts a JWT itself, and holds no JWT secret. For each
protected request it forwards the caller's bearer token to the Authentication Service's
own endpoint (shopease-auth-service/app/routers/auth_routes.py, verify_token):

    POST {AUTH_SERVICE_VERIFY_URL}        Authorization: Bearer <token>, no body
    200 {"valid": true, "user": {"id": int, "full_name": str, "email": str,
                                 "role": str, "is_active": bool}}
    401 {"detail": "Could not validate credentials"}   missing, malformed, wrongly signed or
                                                       expired token, or the user no longer exists
    403 {"detail": "Inactive user"}
    500 / 503                                          failure inside the Authentication Service

Only a 200 response with that exact shape authenticates a caller. Everything else fails
closed. The token is never logged, stored, or included in a response.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

ADMIN_ROLE = "ADMIN"

# Signed 32-bit INT: the type of users.id in the Authentication Service and of
# user_profiles.auth_user_id here.
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
    """The caller, as confirmed by the Authentication Service for this request.

    auth_user_id is that service's user ID. It is the only identity this service uses,
    and it never comes from the request body, query, or path.
    """

    auth_user_id: int
    full_name: str
    email: str
    role: str


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


def _auth_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Authentication service unavailable",
    )


def verify_access_token(token: str, client: httpx.Client) -> AuthenticatedUser:
    """Ask the Authentication Service whether the token is valid. Raise HTTPException if not."""
    if not token or len(token) > MAX_TOKEN_LENGTH:
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
    """Dependency for protected routes: the caller confirmed by the Authentication Service.

    Usage:  user: AuthenticatedUser = Depends(get_current_authenticated_user)
    """
    if credentials is None:
        raise _unauthenticated()
    return verify_access_token(credentials.credentials, client)


def require_admin(
    user: AuthenticatedUser = Depends(get_current_authenticated_user),
) -> AuthenticatedUser:
    """Dependency: allow only callers whose current role in the Authentication Service is ADMIN."""
    if user.role != ADMIN_ROLE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user
