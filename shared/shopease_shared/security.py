"""Verification of auth_service JWTs (RS256) and FastAPI dependencies built on it.

Trust model (docs/security_model.md):
- Identity comes only from a token whose signature verifies against auth_service's public
  keys (JWKS). Identity headers sent by clients are never trusted.
- Access tokens (`token_use=access`, audience `JWT_AUDIENCE`) identify end users.
- Service tokens (`token_use=service`, audience `JWT_SERVICE_AUDIENCE`, `sub=svc:<name>`)
  identify internal callers on /internal/*; a forwarded user token rides in `X-User-Token`.
- Verification proves identity only. Each service still authorizes (role, scope, ownership).
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Protocol

import jwt
from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool

from shopease_shared.errors import ShopEaseError
from shopease_shared.settings import BaseServiceSettings

logger = logging.getLogger("shopease.security")

ALGORITHM = "RS256"
USER_TOKEN_HEADER = "X-User-Token"
_REQUIRED_CLAIMS = ["exp", "iat", "iss", "aud", "sub", "jti"]
_BEARER = {"WWW-Authenticate": "Bearer"}


class KeyProvider(Protocol):
    def get_key(self, kid: str | None) -> Any:
        """Return the public key for `kid`, or raise KeyError if it is unknown."""


class StaticKeyProvider:
    """Fixed public keys (auth_service verifying its own tokens, and tests)."""

    def __init__(self, keys: dict[str, Any]) -> None:
        self._keys = keys

    def get_key(self, kid: str | None) -> Any:
        return self._keys[kid]


class JWKSKeyProvider:
    """Public keys fetched from auth_service's JWKS endpoint and cached.

    An unknown `kid` triggers one refetch (key rotation). Auth Service is therefore not on
    the request path: tokens keep verifying from the cache while it is down.
    """

    def __init__(self, url: str, cache_seconds: int = 300, timeout_seconds: float = 3.0) -> None:
        self._client = jwt.PyJWKClient(
            url, cache_jwk_set=True, lifespan=cache_seconds, timeout=timeout_seconds
        )

    def get_key(self, kid: str | None) -> Any:
        if kid is None:
            raise KeyError(kid)
        try:
            return self._client.get_signing_key(kid).key
        except jwt.PyJWKClientConnectionError as exc:
            logger.warning("JWKS fetch failed", extra={"error": repr(exc)})
            raise ShopEaseError(
                503, "AUTH_UNAVAILABLE", "Token verification is temporarily unavailable."
            ) from exc
        except jwt.PyJWKClientError as exc:
            raise KeyError(kid) from exc


@dataclass(frozen=True)
class Principal:
    subject: str
    token_use: str
    role: str | None = None
    scopes: frozenset[str] = field(default_factory=frozenset)
    token_id: str | None = None

    @property
    def user_id(self) -> uuid.UUID:
        return uuid.UUID(self.subject)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def unauthenticated(code: str = "UNAUTHENTICATED", message: str = "A valid bearer token is required.") -> ShopEaseError:
    return ShopEaseError(401, code, message, headers=_BEARER)


class TokenVerifier:
    def __init__(
        self,
        key_provider: KeyProvider,
        issuer: str,
        audience: str,
        service_audience: str,
        leeway_seconds: int = 30,
    ) -> None:
        self.key_provider = key_provider
        self.issuer = issuer
        self.audiences = {"access": audience, "service": service_audience}
        self.leeway = leeway_seconds

    @classmethod
    def from_settings(cls, settings: BaseServiceSettings, key_provider: KeyProvider | None = None) -> "TokenVerifier":
        return cls(
            key_provider or JWKSKeyProvider(settings.jwks_url, settings.jwks_cache_seconds),
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            service_audience=settings.jwt_service_audience,
            leeway_seconds=settings.jwt_leeway_seconds,
        )

    def verify(self, token: str, token_use: str) -> Principal:
        """Verify signature, algorithm, issuer, audience, expiry and token type."""
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != ALGORITHM:
                raise jwt.InvalidAlgorithmError(header.get("alg"))
            key = self.key_provider.get_key(header.get("kid"))
            claims = jwt.decode(
                token,
                key,
                algorithms=[ALGORITHM],
                audience=self.audiences[token_use],
                issuer=self.issuer,
                leeway=self.leeway,
                options={"require": _REQUIRED_CLAIMS},
            )
        except jwt.ExpiredSignatureError as exc:
            raise unauthenticated("TOKEN_EXPIRED", "The access token has expired.") from exc
        except (jwt.InvalidTokenError, KeyError) as exc:
            # The token itself is never logged.
            logger.info("token rejected", extra={"reason": type(exc).__name__})
            raise unauthenticated("INVALID_TOKEN", "The access token is invalid.") from exc

        if claims.get("token_use") != token_use:
            raise unauthenticated("INVALID_TOKEN", "The access token is invalid.")
        if token_use == "access":
            try:
                uuid.UUID(claims["sub"])
            except ValueError as exc:
                raise unauthenticated("INVALID_TOKEN", "The access token is invalid.") from exc
        return Principal(
            subject=claims["sub"],
            token_use=token_use,
            role=claims.get("role"),
            scopes=frozenset(str(claims.get("scope", "")).split()),
            token_id=claims["jti"],
        )


def bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthenticated()
    return token.strip()


def _verifier(request: Request) -> TokenVerifier:
    return request.app.state.token_verifier


async def current_user(request: Request) -> Principal:
    """The end user, from a verified access token. Key fetches run off the event loop."""
    token = bearer_token(request)
    return await run_in_threadpool(_verifier(request).verify, token, "access")


async def optional_user(request: Request) -> Principal | None:
    """For public routes that show more to some callers (e.g. admins see archived products).

    No Authorization header means anonymous. A header that is present but invalid is still
    rejected with 401, so a broken token never silently downgrades to anonymous.
    """
    if "authorization" not in request.headers:
        return None
    return await current_user(request)


async def current_service(request: Request) -> Principal:
    """The calling internal service, from a verified service token."""
    token = bearer_token(request)
    return await run_in_threadpool(_verifier(request).verify, token, "service")


async def forwarded_user(request: Request) -> Principal:
    """The end user an internal call acts for: a verified access token in X-User-Token."""
    token = request.headers.get(USER_TOKEN_HEADER, "").strip()
    if not token:
        raise unauthenticated("UNAUTHENTICATED", f"The {USER_TOKEN_HEADER} header is required.")
    return await run_in_threadpool(_verifier(request).verify, token, "access")


CurrentUser = Annotated[Principal, Depends(current_user)]
OptionalUser = Annotated[Principal | None, Depends(optional_user)]
CurrentService = Annotated[Principal, Depends(current_service)]
ForwardedUser = Annotated[Principal, Depends(forwarded_user)]


def require_admin(user: CurrentUser) -> Principal:
    if not user.is_admin:
        raise ShopEaseError(403, "FORBIDDEN", "This action requires the admin role.")
    return user


AdminUser = Annotated[Principal, Depends(require_admin)]


def require_scope(scope: str) -> Callable[[Principal], Principal]:
    def dependency(service: CurrentService) -> Principal:
        if scope not in service.scopes:
            raise ShopEaseError(403, "INSUFFICIENT_SCOPE", f"The service token lacks the '{scope}' scope.")
        return service

    return dependency
