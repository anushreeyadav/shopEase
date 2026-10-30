"""Test-only token minting with a throwaway RSA key (auth_service signs real tokens)."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from shopease_shared.security import StaticKeyProvider

KID = "test-key"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KEY_PROVIDER = StaticKeyProvider({KID: KEY.public_key()})


def make_token(
    sub: str | uuid.UUID | None = None,
    *,
    role: str = "customer",
    token_use: str = "access",
    aud: str | None = None,
    iss: str = "shopease-auth",
    expires_in: int = 300,
    scope: str | None = None,
    key=KEY,
    kid: str = KID,
    algorithm: str = "RS256",
) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": iss,
        "aud": aud or ("shopease-api" if token_use == "access" else "shopease-internal"),
        "sub": str(sub or uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
        "jti": uuid.uuid4().hex,
        "token_use": token_use,
    }
    if token_use == "access":
        payload["role"] = role
    if scope is not None:
        payload["scope"] = scope
    if algorithm == "none":
        return jwt.encode(payload, None, algorithm="none")
    return jwt.encode(payload, key, algorithm=algorithm, headers={"kid": kid})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
