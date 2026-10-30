"""Authentication Service configuration, read from environment variables (and .env in development)."""

from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr
from sqlalchemy.engine import URL

from shopease_shared import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "auth_service"

    # This service's own logical database (auth_db). No other service receives these credentials.
    mysql_host: str = Field(default="localhost", validation_alias=AliasChoices("MYSQL_HOST"))
    mysql_port: int = Field(default=3306, validation_alias=AliasChoices("MYSQL_PORT"))
    db_name: str = Field(default="auth_db", validation_alias=AliasChoices("AUTH_DB_NAME"))
    # Runtime user: SELECT/INSERT/UPDATE/DELETE on auth_db only. Used by the running service.
    db_user: str = Field(default="auth_svc", validation_alias=AliasChoices("AUTH_DB_USER"))
    db_password: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("AUTH_DB_PASSWORD")
    )
    # Migration user: DDL on auth_db only. Used by Alembic, never by the running service.
    db_migration_user: str = Field(
        default="auth_migrator", validation_alias=AliasChoices("AUTH_DB_MIGRATION_USER")
    )
    db_migration_password: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("AUTH_DB_MIGRATION_PASSWORD")
    )
    db_connect_timeout_seconds: int = Field(
        default=3, validation_alias=AliasChoices("DB_CONNECT_TIMEOUT_SECONDS")
    )
    db_pool_size: int = Field(default=5, validation_alias=AliasChoices("DB_POOL_SIZE"))

    # Token signing (RS256). The private key comes from a file or the environment, never Git.
    # Without one, development and test runs generate a temporary key (tokens stop
    # verifying after a restart); any other environment refuses to start.
    jwt_private_key_path: str | None = Field(
        default=None, validation_alias=AliasChoices("JWT_PRIVATE_KEY_PATH")
    )
    jwt_private_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("JWT_PRIVATE_KEY")
    )
    jwt_key_id: str = Field(default="shopease-1", validation_alias=AliasChoices("JWT_KEY_ID"))
    access_token_minutes: int = Field(
        default=15, ge=1, le=60, validation_alias=AliasChoices("JWT_ACCESS_TOKEN_MINUTES")
    )
    service_token_minutes: int = Field(
        default=5, ge=1, le=30, validation_alias=AliasChoices("JWT_SERVICE_TOKEN_MINUTES")
    )
    refresh_token_days: int = Field(
        default=14, ge=1, le=90, validation_alias=AliasChoices("REFRESH_TOKEN_DAYS")
    )

    # Brute-force protection per account (the gateway also rate-limits per client IP).
    max_failed_logins: int = Field(default=5, ge=1, validation_alias=AliasChoices("MAX_FAILED_LOGINS"))
    lockout_minutes: int = Field(default=15, ge=1, validation_alias=AliasChoices("LOCKOUT_MINUTES"))

    def _url(self, user: str, password: SecretStr) -> URL:
        # URL objects mask the password when printed or logged.
        return URL.create(
            "mysql+pymysql",
            username=user,
            password=password.get_secret_value(),
            host=self.mysql_host,
            port=self.mysql_port,
            database=self.db_name,
            query={"charset": "utf8mb4"},
        )

    @property
    def database_url(self) -> URL:
        return self._url(self.db_user, self.db_password)

    @property
    def migration_database_url(self) -> URL:
        if not self.db_migration_password.get_secret_value():
            raise RuntimeError(
                "AUTH_DB_MIGRATION_USER and AUTH_DB_MIGRATION_PASSWORD must be set to run migrations."
            )
        return self._url(self.db_migration_user, self.db_migration_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()
