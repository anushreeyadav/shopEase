"""Account rules for auth_service. Routes stay thin; every rule lives here.

Logs carry user IDs and outcomes only: never emails, passwords or tokens.
"""

import logging
import uuid
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuthUser, RefreshToken, Role, ServiceClient, UserStatus
from app.models.base import utcnow
from app.security.passwords import hash_password, needs_rehash, verify_password
from app.security.tokens import TokenIssuer, hash_refresh_token, new_refresh_token
from shopease_shared import ShopEaseError

logger = logging.getLogger(__name__)

def invalid_credentials() -> ShopEaseError:
    # The same answer for an unknown email and a wrong password (no account enumeration).
    return ShopEaseError(401, "INVALID_CREDENTIALS", "Email or password is incorrect.")


def invalid_refresh_token() -> ShopEaseError:
    return ShopEaseError(401, "INVALID_REFRESH_TOKEN", "The refresh token is invalid or expired.")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def register(session: Session, email: str, password: str) -> AuthUser:
    user = AuthUser(email=normalize_email(email), password_hash=hash_password(password))
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ShopEaseError(
            409, "EMAIL_ALREADY_REGISTERED", "An account with this email already exists."
        ) from exc
    logger.info("account registered", extra={"user_id": str(user.id)})
    return user


def _issue_session(session: Session, issuer: TokenIssuer, user: AuthUser) -> tuple[dict, RefreshToken]:
    raw, token_hash = new_refresh_token()
    row = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=utcnow() + timedelta(days=issuer.settings.refresh_token_days),
    )
    session.add(row)
    access_token, expires_in = issuer.access_token(user)
    tokens = {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "refresh_token": raw,
    }
    return tokens, row


def login(session: Session, settings: Settings, issuer: TokenIssuer, email: str, password: str) -> dict:
    user = session.scalars(
        select(AuthUser).where(AuthUser.email == normalize_email(email)).with_for_update()
    ).one_or_none()
    now = utcnow()

    if user is not None and user.locked_until is not None and user.locked_until > now:
        # Every attempt is refused while locked, even with the right password.
        retry_after = int((user.locked_until - now).total_seconds()) + 1
        raise ShopEaseError(
            423,
            "ACCOUNT_LOCKED",
            "Too many failed attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    if not verify_password(user.password_hash if user else None, password):
        if user is not None:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.max_failed_logins:
                user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
                user.failed_login_attempts = 0
                logger.warning("account locked", extra={"user_id": str(user.id)})
            session.commit()
        logger.info("login failed", extra={"user_id": str(user.id) if user else None})
        raise invalid_credentials()

    if user.status is not UserStatus.ACTIVE:
        raise ShopEaseError(403, "ACCOUNT_DISABLED", "This account is disabled.")

    user.failed_login_attempts = 0
    user.locked_until = None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    tokens, _ = _issue_session(session, issuer, user)
    session.commit()
    logger.info("login succeeded", extra={"user_id": str(user.id)})
    return tokens


def refresh(session: Session, issuer: TokenIssuer, raw_token: str) -> dict:
    """Rotate a refresh token. Reusing a rotated token revokes the whole family."""
    token = session.scalars(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token)).with_for_update()
    ).one_or_none()
    now = utcnow()
    if token is None or token.expires_at <= now:
        raise invalid_refresh_token()
    if token.revoked_at is not None:
        # A revoked token was presented again: it may have been stolen. End every session.
        revoke_all(session, token.user_id)
        session.commit()
        logger.warning("refresh token reuse detected", extra={"user_id": str(token.user_id)})
        raise invalid_refresh_token()

    user = session.get(AuthUser, token.user_id)
    if user is None or user.status is not UserStatus.ACTIVE:
        raise invalid_refresh_token()

    tokens, replacement = _issue_session(session, issuer, user)
    session.flush()
    token.revoked_at = now
    token.replaced_by_id = replacement.id
    session.commit()
    return tokens


def revoke_all(session: Session, user_id: uuid.UUID) -> None:
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def logout(session: Session, user_id: uuid.UUID, raw_token: str | None) -> None:
    """Revoke one refresh token (this device) or, without one, every session of the user.

    Access tokens are not stored; one already issued stays valid until it expires
    (JWT_ACCESS_TOKEN_MINUTES).
    """
    if raw_token is None:
        revoke_all(session, user_id)
    else:
        session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.token_hash == hash_refresh_token(raw_token),
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=utcnow())
        )
    session.commit()


def change_password(session: Session, user_id: uuid.UUID, current: str, new: str) -> None:
    user = session.get(AuthUser, user_id, with_for_update=True)
    if user is None or not verify_password(user.password_hash, current):
        raise invalid_credentials()
    user.password_hash = hash_password(new)
    revoke_all(session, user.id)
    session.commit()
    logger.info("password changed", extra={"user_id": str(user.id)})


def set_role(session: Session, user_id: uuid.UUID, role: Role, changed_by: uuid.UUID) -> AuthUser:
    user = session.get(AuthUser, user_id, with_for_update=True)
    if user is None:
        raise ShopEaseError(404, "USER_NOT_FOUND", "No such user.")
    user.role = role
    # The new role applies to tokens issued from now on; existing ones keep the old claim
    # until they expire (at most JWT_ACCESS_TOKEN_MINUTES).
    session.commit()
    logger.info("role changed", extra={"user_id": str(user.id), "role": role.value, "by": str(changed_by)})
    return user


def authenticate_client(session: Session, client_id: str, secret: str, requested: list[str] | None) -> list[str]:
    client = session.get(ServiceClient, client_id)
    if client is None or not client.active or not verify_password(client.secret_hash, secret):
        if client is None:
            verify_password(None, secret)  # equal timing for unknown clients
        logger.warning("service client authentication failed", extra={"client_id": client_id})
        raise ShopEaseError(401, "INVALID_CLIENT", "Client authentication failed.")
    allowed = set(client.allowed_scopes)
    scopes = set(requested) if requested else allowed
    if not scopes <= allowed:
        raise ShopEaseError(403, "SCOPE_NOT_ALLOWED", "A requested scope is not allowed for this client.")
    return sorted(scopes)
