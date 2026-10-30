"""Issuing access tokens, service tokens and opaque refresh tokens."""

import hashlib
import secrets
import uuid
from datetime import timedelta

import jwt

from app.config import Settings
from app.models import AuthUser
from app.models.base import utcnow
from app.security.keys import SigningKey


def hash_refresh_token(raw: str) -> str:
    # Refresh tokens are 256-bit random values, so a plain SHA-256 is enough to store them.
    return hashlib.sha256(raw.encode()).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    """(raw token for the client, hash for the database)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_refresh_token(raw)


class TokenIssuer:
    def __init__(self, settings: Settings, key: SigningKey) -> None:
        self.settings = settings
        self.key = key

    def _sign(self, claims: dict, lifetime: timedelta) -> str:
        now = utcnow()
        payload = {
            "iss": self.settings.jwt_issuer,
            "iat": now,
            "nbf": now,
            "exp": now + lifetime,
            "jti": uuid.uuid4().hex,
            **claims,
        }
        return jwt.encode(payload, self.key.private_key, algorithm="RS256", headers={"kid": self.key.kid})

    def access_token(self, user: AuthUser) -> tuple[str, int]:
        lifetime = timedelta(minutes=self.settings.access_token_minutes)
        token = self._sign(
            {
                "sub": str(user.id),
                "aud": self.settings.jwt_audience,
                "role": user.role.value,
                "token_use": "access",
            },
            lifetime,
        )
        return token, int(lifetime.total_seconds())

    def service_token(self, client_id: str, scopes: list[str]) -> tuple[str, int]:
        lifetime = timedelta(minutes=self.settings.service_token_minutes)
        token = self._sign(
            {
                "sub": client_id,
                "aud": self.settings.jwt_service_audience,
                "scope": " ".join(sorted(scopes)),
                "token_use": "service",
            },
            lifetime,
        )
        return token, int(lifetime.total_seconds())
