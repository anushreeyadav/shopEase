"""Authentication API tests: registration, login, tokens, sessions and roles (SQLite)."""

import io
import logging
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.pool import StaticPool

from app.cli import create_service_client, promote_admin
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.models import AuthUser, Base, ServiceClient
from app.security.keys import SigningKey
from app.security.passwords import hash_password
from shopease_shared.log_config import JsonFormatter

EMAIL = "asha.rao@example.com"
PASSWORD = "correct-horse-battery"


class Ctx:
    def __init__(self, client: TestClient, db: Database, key: SigningKey):
        self.client, self.db, self.key = client, db, key

    def register(self, email=EMAIL, password=PASSWORD):
        return self.client.post("/api/auth/register", json={"email": email, "password": password})

    def login(self, email=EMAIL, password=PASSWORD):
        return self.client.post("/api/auth/login", json={"email": email, "password": password})

    def tokens(self, email=EMAIL, password=PASSWORD) -> dict:
        self.register(email, password)
        response = self.login(email, password)
        assert response.status_code == 200, response.text
        return response.json()

    def user(self, email=EMAIL) -> AuthUser:
        with self.db.session() as session:
            return session.scalars(select(AuthUser).where(AuthUser.email == email)).one()


@pytest.fixture
def ctx():
    settings = Settings(_env_file=None, APP_ENV="test", MAX_FAILED_LOGINS=3)
    key = SigningKey.generate("test-kid")
    app = create_app(settings, signing_key=key)
    db = Database("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(db.engine)
    app.state.db = db
    with TestClient(app, raise_server_exceptions=False) as client:
        yield Ctx(client, db, key)
    db.dispose()


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def sign(ctx: Ctx, key=None, **overrides) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": "shopease-auth",
        "aud": "shopease-api",
        "sub": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "jti": "j1",
        "role": "customer",
        "token_use": "access",
        **overrides,
    }
    return jwt.encode(claims, key or ctx.key.private_key, algorithm="RS256", headers={"kid": ctx.key.kid})


# --- Registration -------------------------------------------------------------------


def test_register_creates_account_and_never_returns_or_stores_the_password(ctx):
    response = ctx.register()
    assert response.status_code == 201
    assert response.headers["Location"] == "/api/users/me"
    body = response.json()
    assert set(body) == {"user_id", "email", "role", "created_at"}
    assert body["role"] == "customer"
    stored = ctx.user()
    assert stored.password_hash.startswith("$argon2id$")
    assert PASSWORD not in stored.password_hash and PASSWORD not in response.text


def test_duplicate_registration_is_rejected_case_insensitively(ctx):
    assert ctx.register().status_code == 201
    response = ctx.register(email="Asha.Rao@Example.COM")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


@pytest.mark.parametrize(
    "body",
    [
        {"email": EMAIL, "password": "short"},
        {"email": "not-an-email", "password": PASSWORD},
        {"email": EMAIL},
    ],
)
def test_registration_validation_errors_do_not_echo_input(ctx, body):
    response = ctx.client.post("/api/auth/register", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "short" not in response.text and "not-an-email" not in response.text


# --- Login and access tokens ----------------------------------------------------------


def test_login_issues_a_verifiable_access_token(ctx):
    tokens = ctx.tokens()
    assert tokens["token_type"] == "Bearer" and tokens["expires_in"] == 900
    jwks = ctx.client.get("/api/auth/.well-known/jwks.json").json()
    [jwk] = jwks["keys"]
    assert jwk["kid"] == "test-kid" and jwk["kty"] == "RSA" and "d" not in jwk
    claims = jwt.decode(
        tokens["access_token"],
        jwt.PyJWK(jwk).key,
        algorithms=["RS256"],
        audience="shopease-api",
        issuer="shopease-auth",
    )
    assert claims["sub"] == str(ctx.user().id)
    assert claims["role"] == "customer" and claims["token_use"] == "access"
    assert claims["exp"] - claims["iat"] == 900 and claims["jti"]


def test_invalid_login_gives_the_same_answer_for_unknown_email_and_wrong_password(ctx):
    ctx.register()
    wrong_password = ctx.login(password="wrong-password-123")
    unknown_email = ctx.login(email="nobody@example.com")
    for response in (wrong_password, unknown_email):
        assert response.status_code == 401
    strip = lambda r: {k: v for k, v in r.json()["error"].items() if k != "request_id"}  # noqa: E731
    assert strip(wrong_password) == strip(unknown_email) == {
        "code": "INVALID_CREDENTIALS",
        "message": "Email or password is incorrect.",
    }


def test_repeated_failures_lock_the_account_even_for_the_right_password(ctx):
    ctx.register()
    for _ in range(3):
        assert ctx.login(password="wrong-password-123").status_code == 401
    locked = ctx.login()
    assert locked.status_code == 423
    assert locked.json()["error"]["code"] == "ACCOUNT_LOCKED"
    assert int(locked.headers["Retry-After"]) > 0


def test_successful_login_resets_the_failure_counter(ctx):
    ctx.register()
    ctx.login(password="wrong-password-123")
    ctx.login(password="wrong-password-123")
    assert ctx.login().status_code == 200
    assert ctx.user().failed_login_attempts == 0


# --- Token validation on protected routes ----------------------------------------------


@pytest.mark.parametrize(
    "make,code",
    [
        (lambda c: None, "UNAUTHENTICATED"),
        (lambda c: "not-a-jwt", "INVALID_TOKEN"),
        (lambda c: sign(c, exp=datetime.now(UTC) - timedelta(minutes=5)), "TOKEN_EXPIRED"),
        (lambda c: sign(c, key=SigningKey.generate("x").private_key), "INVALID_TOKEN"),
        (lambda c: sign(c, aud="someone-else"), "INVALID_TOKEN"),
        (lambda c: sign(c, iss="evil-issuer"), "INVALID_TOKEN"),
        (lambda c: sign(c, token_use="service", aud="shopease-api"), "INVALID_TOKEN"),
        (lambda c: sign(c, sub="svc:order"), "INVALID_TOKEN"),
        (
            lambda c: jwt.encode(
                {"sub": str(uuid.uuid4()), "aud": "shopease-api", "iss": "shopease-auth"}, None, algorithm="none"
            ),
            "INVALID_TOKEN",
        ),
    ],
    ids=["missing", "garbage", "expired", "wrong-key", "wrong-aud", "wrong-iss", "service-token", "non-uuid-sub", "alg-none"],
)
def test_protected_routes_reject_bad_tokens(ctx, make, code):
    token = make(ctx)
    headers = bearer(token) if token else {}
    response = ctx.client.post("/api/auth/logout", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == code
    assert response.headers["WWW-Authenticate"] == "Bearer"


# --- Refresh, logout, password change ------------------------------------------------


def test_refresh_rotates_and_reuse_revokes_the_whole_session(ctx):
    first = ctx.tokens()
    rotated = ctx.client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert rotated.status_code == 200
    second = rotated.json()
    assert second["refresh_token"] != first["refresh_token"]

    reuse = ctx.client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert reuse.status_code == 401 and reuse.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"
    # The theft response also revoked the token issued by the rotation.
    after = ctx.client.post("/api/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert after.status_code == 401


def test_logout_revokes_the_refresh_token(ctx):
    tokens = ctx.tokens()
    response = ctx.client.post(
        "/api/auth/logout", headers=bearer(tokens["access_token"]), json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 204
    again = ctx.client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert again.status_code == 401


def test_logout_cannot_revoke_another_users_refresh_token(ctx):
    victim = ctx.tokens()
    attacker = ctx.tokens(email="mallory@example.com")
    ctx.client.post(
        "/api/auth/logout", headers=bearer(attacker["access_token"]), json={"refresh_token": victim["refresh_token"]}
    )
    assert ctx.client.post("/api/auth/refresh", json={"refresh_token": victim["refresh_token"]}).status_code == 200


def test_password_change_requires_the_current_password_and_ends_sessions(ctx):
    tokens = ctx.tokens()
    headers = bearer(tokens["access_token"])
    wrong = ctx.client.put(
        "/api/auth/password", headers=headers, json={"current_password": "nope", "new_password": "another-long-password"}
    )
    assert wrong.status_code == 401
    ok = ctx.client.put(
        "/api/auth/password", headers=headers, json={"current_password": PASSWORD, "new_password": "another-long-password"}
    )
    assert ok.status_code == 204
    assert ctx.login().status_code == 401
    assert ctx.login(password="another-long-password").status_code == 200
    assert ctx.client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401


# --- Roles ----------------------------------------------------------------------------


def test_only_admins_can_change_roles(ctx):
    customer = ctx.tokens()
    target = str(ctx.user().id)
    denied = ctx.client.patch(f"/api/auth/users/{target}/role", headers=bearer(customer["access_token"]), json={"role": "admin"})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "FORBIDDEN"

    ctx.register(email="admin@example.com")
    assert promote_admin(ctx.db, "admin@example.com") == 0
    admin = ctx.login(email="admin@example.com").json()
    granted = ctx.client.patch(f"/api/auth/users/{target}/role", headers=bearer(admin["access_token"]), json={"role": "admin"})
    assert granted.status_code == 200 and granted.json()["role"] == "admin"
    missing = ctx.client.patch(
        f"/api/auth/users/{uuid.uuid4()}/role", headers=bearer(admin["access_token"]), json={"role": "admin"}
    )
    assert missing.status_code == 404


# --- Service tokens (ADR-08) -------------------------------------------------------------


def test_service_token_client_credentials(ctx, capsys):
    assert create_service_client(ctx.db, "svc:order", ["addresses:read", "products:read"], rotate=False) == 0
    secret = capsys.readouterr().out.split("client_secret=")[1].split()[0]
    with ctx.db.session() as session:
        assert session.get(ServiceClient, "svc:order").secret_hash.startswith("$argon2id$")

    ok = ctx.client.post(
        "/internal/auth/service-token",
        json={"client_id": "svc:order", "client_secret": secret, "scope": "addresses:read"},
    )
    assert ok.status_code == 200
    claims = jwt.decode(
        ok.json()["access_token"], ctx.key.public_key, algorithms=["RS256"], audience="shopease-internal"
    )
    assert claims["sub"] == "svc:order" and claims["scope"] == "addresses:read" and claims["token_use"] == "service"

    wrong = ctx.client.post("/internal/auth/service-token", json={"client_id": "svc:order", "client_secret": "x"})
    unknown = ctx.client.post("/internal/auth/service-token", json={"client_id": "svc:nope", "client_secret": "x"})
    assert wrong.status_code == unknown.status_code == 401
    too_much = ctx.client.post(
        "/internal/auth/service-token",
        json={"client_id": "svc:order", "client_secret": secret, "scope": "orders:payment"},
    )
    assert too_much.status_code == 403 and too_much.json()["error"]["code"] == "SCOPE_NOT_ALLOWED"


# --- Logging hygiene --------------------------------------------------------------------


def test_logs_never_contain_passwords_tokens_or_emails(ctx):
    # Format records exactly as production does (JSON, including `extra` fields).
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(JsonFormatter("auth_service"))
    logging.getLogger().addHandler(handler)
    try:
        tokens = ctx.tokens()
        ctx.login(password="wrong-password-123")
        ctx.client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        ctx.client.post("/api/auth/logout", headers=bearer(tokens["access_token"]))
        ctx.client.post("/api/auth/register", json={"email": EMAIL, "password": "short"})
    finally:
        logging.getLogger().removeHandler(handler)
    output = buffer.getvalue()
    assert "login failed" in output and "login succeeded" in output  # logging did happen
    for secret in (PASSWORD, "wrong-password-123", tokens["access_token"], tokens["refresh_token"], EMAIL):
        assert secret not in output


def test_ensure_service_client_is_idempotent_and_never_prints_the_secret(ctx, capsys, monkeypatch):
    from app.cli import ensure_service_client

    secret = "bootstrap-secret-0123456789"
    monkeypatch.setenv("SVC_SECRET", secret)
    assert ensure_service_client(ctx.db, "svc:order", ["products:read"], "SVC_SECRET") == 0
    with ctx.db.session() as session:
        first_hash = session.get(ServiceClient, "svc:order").secret_hash
    assert ensure_service_client(ctx.db, "svc:order", ["products:read", "addresses:read"], "SVC_SECRET") == 0
    with ctx.db.session() as session:
        client = session.get(ServiceClient, "svc:order")
        assert client.secret_hash == first_hash  # same secret: hash kept
        assert client.allowed_scopes == ["addresses:read", "products:read"]
    ok = ctx.client.post("/internal/auth/service-token", json={"client_id": "svc:order", "client_secret": secret})
    assert ok.status_code == 200
    assert secret not in capsys.readouterr().out

    monkeypatch.setenv("SVC_SECRET", "change-me")
    assert ensure_service_client(ctx.db, "svc:order", ["products:read"], "SVC_SECRET") == 1
    assert ensure_service_client(ctx.db, "svc:order", ["products:read"], "UNSET_VARIABLE") == 1


def test_stored_client_secrets_and_passwords_use_argon2id():
    assert hash_password("x" * 12).startswith("$argon2id$")
