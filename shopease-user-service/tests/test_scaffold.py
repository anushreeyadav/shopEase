"""Checks for the project foundation: app startup, service routes, models, and settings.

Token verification is tested in test_auth_integration.py.
"""

import pytest
from pydantic import ValidationError

import app.models  # noqa: F401  (registers the tables, as alembic/env.py does)
from app.core.config import Settings, get_settings
from app.database.connection import Base


def test_root_reports_service(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "ShopEase User Service"


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_models_register_both_tables():
    assert {"user_profiles", "user_addresses"} <= set(Base.metadata.tables)


def test_settings_read_from_environment():
    settings = get_settings()
    assert settings.mysql_database == "shopease_user_db"
    assert str(settings.auth_service_verify_url) == "http://auth.test/api/auth/verify-token"
    assert settings.auth_service_timeout_seconds == 2


def test_secrets_are_masked():
    settings = get_settings()
    assert "test-db-password-not-real" not in repr(settings)
    assert "test-db-password-not-real" not in str(settings.database_url)


def test_placeholder_password_is_rejected_without_echoing_it():
    with pytest.raises(ValidationError) as error:
        Settings(mysql_user="u", mysql_password="change-me-please", _env_file=None)
    assert "change-me-please" not in str(error.value)


def test_no_jwt_secret_setting_exists():
    # The User Service must not hold the Authentication Service's signing key.
    assert not any("jwt" in name or "secret" in name for name in Settings.model_fields)


@pytest.mark.parametrize("prefix", ["api", "C:/Program Files/Git/api", "/api/", "/", "/a pi"])
def test_invalid_api_prefix_is_rejected_at_startup(prefix):
    # Git Bash on Windows rewrites "/api" in exported variables to a Windows path; that must
    # fail as a clear settings error, not later inside FastAPI.
    with pytest.raises(ValidationError) as error:
        Settings(mysql_user="u", mysql_password="p", api_prefix=prefix, _env_file=None)
    assert "api_prefix" in str(error.value)


@pytest.mark.parametrize("prefix", ["/api", "/api/v1", "/user-service"])
def test_valid_api_prefixes(prefix):
    assert Settings(mysql_user="u", mysql_password="p", api_prefix=prefix, _env_file=None).api_prefix == prefix
