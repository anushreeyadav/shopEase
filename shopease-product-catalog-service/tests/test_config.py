"""Configuration: defaults, environment variables, .env files, and validation of every setting."""

from pathlib import Path

import pytest
from dotenv import dotenv_values
from pydantic import ValidationError

from app.core.config import DEFAULT_SERVICE_PORT, RESERVED_SHOPEASE_PORTS, Settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIRED = {"mysql_user": "catalog_svc", "mysql_password": "a-real-looking-password-123"}


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Remove every setting from the environment, so each test sees only what it sets."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


def make(**values) -> Settings:
    """Settings from keyword values only: no .env file and no environment variables."""
    return Settings(_env_file=None, **{**REQUIRED, **values})


def error_fields(exc: ValidationError) -> set[str]:
    return {str(error["loc"][0]) for error in exc.errors()}


# --- Defaults ---

def test_defaults():
    settings = make()
    assert settings.app_name == "ShopEase Product Catalog Service"
    assert settings.app_version == "1.0.0"
    assert settings.mysql_database == "shopease_product_catalog_db"
    assert settings.mysql_port == 3310
    assert settings.service_port == DEFAULT_SERVICE_PORT == 8006
    assert settings.service_host == "127.0.0.1"
    assert str(settings.auth_service_verify_url) == "http://127.0.0.1:8001/api/auth/verify-token"
    assert settings.jwt_algorithm == "HS256"
    assert settings.low_stock_threshold == 5


def test_default_port_is_not_used_by_another_shopease_service():
    # 8003 is the Product Service and 8004 the Order Service, so the default had to move.
    assert {8003, 8004} <= RESERVED_SHOPEASE_PORTS
    assert DEFAULT_SERVICE_PORT not in RESERVED_SHOPEASE_PORTS


# --- Sources: environment variables and .env ---

def test_reads_environment_variables(monkeypatch):
    monkeypatch.setenv("MYSQL_USER", "env_user")
    monkeypatch.setenv("MYSQL_PASSWORD", "env-password-value")
    monkeypatch.setenv("MYSQL_HOST", "db.internal")
    monkeypatch.setenv("MYSQL_PORT", "3399")
    monkeypatch.setenv("MYSQL_DATABASE", "catalog_test_db")
    monkeypatch.setenv("SERVICE_PORT", "8010")
    monkeypatch.setenv("LOW_STOCK_THRESHOLD", "12")
    monkeypatch.setenv("JWT_ALGORITHM", "HS512")
    monkeypatch.setenv("AUTH_SERVICE_VERIFY_URL", "http://auth.internal:9001/api/auth/verify-token")

    settings = Settings(_env_file=None)
    assert (settings.mysql_user, settings.mysql_host, settings.mysql_port) == ("env_user", "db.internal", 3399)
    assert settings.mysql_database == "catalog_test_db"
    assert settings.mysql_password.get_secret_value() == "env-password-value"
    assert (settings.service_port, settings.low_stock_threshold, settings.jwt_algorithm) == (8010, 12, "HS512")
    assert settings.auth_service_verify_url.host == "auth.internal"


def test_reads_env_file_and_environment_wins(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MYSQL_USER=file_user\nMYSQL_PASSWORD=file-password-value\nLOW_STOCK_THRESHOLD=3\nSERVICE_PORT=8020\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SERVICE_PORT", "8030")

    settings = Settings(_env_file=env_file)
    assert settings.mysql_user == "file_user"
    assert settings.low_stock_threshold == 3
    assert settings.service_port == 8030  # environment variable overrides .env


# --- Secrets ---

def test_database_credentials_have_no_defaults():
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None)
    assert {"mysql_user", "mysql_password"} <= error_fields(caught.value)


@pytest.mark.parametrize("placeholder", ["change-me", "CHANGE-ME", "change-me-please", " change-me"])
def test_placeholder_password_is_rejected(placeholder):
    with pytest.raises(ValidationError) as caught:
        make(mysql_password=placeholder)
    assert error_fields(caught.value) == {"mysql_password"}


def test_empty_password_is_rejected():
    with pytest.raises(ValidationError):
        make(mysql_password="")


def test_password_never_appears_in_output_or_errors():
    secret = "Sup3r-Secret-Value!"
    settings = make(mysql_password=secret)
    assert secret not in repr(settings)
    assert secret not in str(settings.database_url)
    # A rejected value must not be echoed in the error either.
    with pytest.raises(ValidationError) as caught:
        make(mysql_password=secret, mysql_port="not-a-port")
    assert secret not in str(caught.value)
    assert "not-a-port" not in str(caught.value)


def test_no_jwt_secret_setting_exists():
    """The Authentication Service alone holds the signing secret; this service must not ask for it."""
    assert not [name for name in Settings.model_fields if "secret" in name or "key" in name]


def test_database_url_is_built_from_settings():
    url = make(mysql_password="p@ss:w/rd#1", mysql_host="db", mysql_port=3311).database_url
    assert (url.drivername, url.host, url.port, url.database) == ("mysql+pymysql", "db", 3311, "shopease_product_catalog_db")
    assert url.password == "p@ss:w/rd#1"  # special characters are kept intact, not mangled


# --- Validation of individual settings ---

@pytest.mark.parametrize("port", sorted(RESERVED_SHOPEASE_PORTS))
def test_ports_of_other_shopease_services_are_rejected(port):
    with pytest.raises(ValidationError) as caught:
        make(service_port=port)
    assert error_fields(caught.value) == {"service_port"}


@pytest.mark.parametrize(("field", "value"), [
    ("service_port", 0),
    ("service_port", 70000),
    ("service_port", "abc"),
    ("mysql_port", 0),
    ("mysql_port", 65536),
    ("low_stock_threshold", -1),
    ("low_stock_threshold", "five"),
    ("low_stock_threshold", 1_000_000_001),
    ("auth_service_timeout_seconds", 0),
    ("auth_service_timeout_seconds", 31),
    ("auth_service_verify_url", "not a url"),
    ("auth_service_verify_url", "ftp://auth/verify"),
    ("jwt_algorithm", "none"),
    ("jwt_algorithm", "RS256"),   # shopease-auth-service signs only with HMAC
    ("mysql_database", "catalog; DROP DATABASE x"),
    ("mysql_database", ""),
    ("mysql_user", ""),
    ("api_prefix", "api"),
    ("api_prefix", "/api/"),
    ("app_env", "prod"),
    ("log_level", "TRACE"),
])
def test_invalid_values_are_rejected(field, value):
    with pytest.raises(ValidationError) as caught:
        make(**{field: value})
    assert field in error_fields(caught.value)


@pytest.mark.parametrize("algorithm", ["HS256", "HS384", "HS512"])
def test_supported_jwt_algorithms(algorithm):
    assert make(jwt_algorithm=algorithm).jwt_algorithm == algorithm


def test_zero_low_stock_threshold_is_allowed():
    assert make(low_stock_threshold=0).low_stock_threshold == 0


# --- Committed files ---

def test_env_example_has_only_placeholders_and_known_settings():
    values = dotenv_values(PROJECT_ROOT / ".env.example")
    # Every password is a placeholder, so the example cannot be used as-is.
    for key, value in values.items():
        if "PASSWORD" in key or "SECRET" in key:
            assert value.startswith("change-me"), key
    # Every key is a setting, or one of the documented Docker-only keys.
    docker_only = {"MYSQL_ROOT_PASSWORD", "DOCKER_AUTH_SERVICE_VERIFY_URL"}
    known = {name.upper() for name in Settings.model_fields} | docker_only
    assert set(values) <= known, set(values) - known
    # And the example documents every setting.
    assert {name.upper() for name in Settings.model_fields} <= set(values)


def test_env_example_refuses_to_start_unchanged():
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=PROJECT_ROOT / ".env.example")
    assert error_fields(caught.value) == {"mysql_password"}


def test_env_example_is_valid_once_placeholders_are_replaced(tmp_path):
    text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(text.replace("=change-me", "=replaced-password-value"), encoding="utf-8")
    settings = Settings(_env_file=env_file)
    assert settings.mysql_database == "shopease_product_catalog_db"
    assert settings.service_port == 8006


def test_env_file_is_ignored_by_git_and_docker():
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in gitignore and ".env.*" in gitignore and "!.env.example" in gitignore
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in dockerignore
