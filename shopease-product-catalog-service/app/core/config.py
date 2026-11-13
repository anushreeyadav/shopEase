"""Centralised application settings, loaded from environment variables and the .env file.

Environment variables take precedence over .env. Nothing secret has a default value, and a
placeholder ("change-me...") is rejected, so the service cannot start with example credentials.

Token settings mirror the ShopEase Authentication Service (shopease-auth-service):
  - It signs access tokens with HMAC (JWT_ALGORITHM, default HS256) and one shared secret.
  - It verifies them, and checks that the user still exists and is active, at
    POST /api/auth/verify-token.
This service calls that endpoint for every protected request and never holds the signing secret.
JWT_ALGORITHM is used only for a local pre-check that rejects malformed tokens early.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

# Ports of the other ShopEase services on this machine. Listed so the default cannot collide:
#   8000 gateway, 8001 auth, 8002 user, 8003 product, 8004 order, 8005 payment.
RESERVED_SHOPEASE_PORTS = frozenset({8000, 8001, 8002, 8003, 8004, 8005})
DEFAULT_SERVICE_PORT = 8006

# Same upper limit as stock quantities (MAX_STOCK in app/schemas/product_schema.py).
MAX_LOW_STOCK_THRESHOLD = 1_000_000_000

_PLACEHOLDER_PREFIX = "change-me"


class Settings(BaseSettings):
    # hide_input_in_errors: a rejected value must not appear in a startup error or log.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    # --- Application ---
    app_name: str = "ShopEase Product Catalog Service"
    app_version: str = "1.0.0"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "debug", "info", "warning", "error"] = "INFO"
    # Must start with "/" and not end with one, for example "/api".
    api_prefix: str = Field("/api", pattern=r"^/[A-Za-z0-9_\-/]*[A-Za-z0-9_\-]$")
    docs_enabled: bool = True

    # --- Server (used by `python -m app` and the Docker image) ---
    # 127.0.0.1 locally; the Docker image sets 0.0.0.0 so the published port can reach it.
    service_host: str = Field("127.0.0.1", min_length=1)
    service_port: int = Field(default=DEFAULT_SERVICE_PORT, ge=1, le=65535)

    # --- Database (MySQL 8) ---
    # Letters, digits and underscores only: it is also checked by alembic/env.py before migrating.
    mysql_database: str = Field("shopease_product_catalog_db", pattern=r"^[A-Za-z0-9_]{1,64}$")
    mysql_user: str = Field(min_length=1, max_length=32)
    # SecretStr keeps the password masked in repr() and logs. It has no default.
    mysql_password: SecretStr = Field(min_length=1)
    mysql_host: str = Field("127.0.0.1", min_length=1)
    # 3310: the other ShopEase MySQL instances use 3306, 3308 and 3309.
    mysql_port: int = Field(default=3310, ge=1, le=65535)

    # --- Authentication Service and token verification ---
    auth_service_verify_url: HttpUrl = HttpUrl("http://127.0.0.1:8001/api/auth/verify-token")
    auth_service_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    # Must equal JWT_ALGORITHM in shopease-auth-service. It accepts only these HMAC algorithms.
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"

    # --- Inventory ---
    # An active product is reported as low on stock when stock_quantity is at or below this.
    low_stock_threshold: int = Field(default=5, ge=0, le=MAX_LOW_STOCK_THRESHOLD)

    @field_validator("mysql_password")
    @classmethod
    def reject_placeholder(cls, value: SecretStr) -> SecretStr:
        if value.get_secret_value().strip().lower().startswith(_PLACEHOLDER_PREFIX):
            raise ValueError("replace the placeholder value from .env.example")
        return value

    @field_validator("service_port")
    @classmethod
    def avoid_other_shopease_services(cls, value: int) -> int:
        if value in RESERVED_SHOPEASE_PORTS:
            raise ValueError(f"port {value} is used by another ShopEase service")
        return value

    @property
    def database_url(self) -> URL:
        """Connection URL. URL.create escapes special characters, and str(URL) masks the password."""
        return URL.create(
            "mysql+pymysql",
            username=self.mysql_user,
            password=self.mysql_password.get_secret_value(),
            host=self.mysql_host,
            port=self.mysql_port,
            database=self.mysql_database,
        )


@lru_cache
def get_settings() -> Settings:
    """Return one cached Settings instance for the whole process."""
    return Settings()
