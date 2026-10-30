"""The RS256 signing key and its public JWKS representation."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SigningKey:
    kid: str
    private_key: rsa.RSAPrivateKey

    @property
    def public_key(self) -> rsa.RSAPublicKey:
        return self.private_key.public_key()

    def public_jwk(self) -> dict[str, Any]:
        jwk = json.loads(RSAAlgorithm.to_jwk(self.public_key))
        return {**jwk, "kid": self.kid, "alg": "RS256", "use": "sig"}

    @classmethod
    def generate(cls, kid: str) -> "SigningKey":
        return cls(kid, rsa.generate_private_key(public_exponent=65537, key_size=2048))

    @classmethod
    def from_pem(cls, kid: str, pem: bytes) -> "SigningKey":
        key = serialization.load_pem_private_key(pem, password=None)
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
            raise ValueError("JWT signing key must be an RSA private key of at least 2048 bits.")
        return cls(kid, key)


def load_signing_key(settings: Settings) -> SigningKey:
    if settings.jwt_private_key is not None:
        return SigningKey.from_pem(settings.jwt_key_id, settings.jwt_private_key.get_secret_value().encode())
    if settings.jwt_private_key_path:
        return SigningKey.from_pem(settings.jwt_key_id, Path(settings.jwt_private_key_path).read_bytes())
    if settings.environment in ("development", "test"):
        logger.warning(
            "no JWT signing key configured; using a temporary key for this process only "
            "(set JWT_PRIVATE_KEY_PATH, see scripts/generate_jwt_key.py)"
        )
        return SigningKey.generate(settings.jwt_key_id)
    raise RuntimeError("JWT_PRIVATE_KEY_PATH or JWT_PRIVATE_KEY must be set outside development.")
