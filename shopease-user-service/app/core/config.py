"""Application settings, loaded from environment variables and the .env file.

Environment variables take precedence over .env. Nothing secret has a default value.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    # hide_input_in_errors: a rejected value must not appear in a startup error or log.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    app_name: str = "ShopEase User Service"
    app_version: str = "0.1.0"
    app_env: str = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "debug", "info", "warning", "error"] = "INFO"
    # Must start with "/" and not end with one, for example "/api".
    api_prefix: str = Field("/api", pattern=r"^/[A-Za-z0-9_\-/]*[A-Za-z0-9_\-]$")
    docs_enabled: bool = True

    mysql_database: str = "shopease_user_db"
    mysql_user: str
    # SecretStr keeps the password masked in repr() and logs. It has no default.
    mysql_password: SecretStr
    mysql_host: str = "127.0.0.1"
    mysql_port: int = Field(default=3309, ge=1, le=65535)

    # The Authentication Service's own endpoint: POST /api/auth/verify-token (see app/core/security.py).
    # This service holds no JWT secret; the Authentication Service checks every token.
    auth_service_verify_url: HttpUrl = HttpUrl("http://127.0.0.1:8001/api/auth/verify-token")
    auth_service_timeout_seconds: float = Field(default=5.0, gt=0, le=30)

    @field_validator("mysql_password")
    @classmethod
    def reject_placeholder(cls, value: SecretStr) -> SecretStr:
        if value.get_secret_value().lower().startswith("change-me"):
            raise ValueError("replace the placeholder value from .env.example")
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
