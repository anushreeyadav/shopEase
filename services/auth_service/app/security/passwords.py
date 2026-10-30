"""Password hashing with Argon2id (argon2-cffi, RFC 9106 parameters)."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

# Verified against when the email is unknown, so both failure paths take similar time.
_DUMMY_HASH = _hasher.hash("shopease-timing-equalizer")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash uses older parameters than the current defaults."""
    return _hasher.check_needs_rehash(password_hash)
