"""User Service configuration, read from environment variables (and .env in development)."""

from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr
from sqlalchemy.engine import URL

from shopease_shared import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "user_service"

    # This service's own logical database (user_db). No other service receives these credentials.
    mysql_host: str = Field(default="localhost", validation_alias=AliasChoices("MYSQL_HOST"))
    mysql_port: int = Field(default=3306, validation_alias=AliasChoices("MYSQL_PORT"))
    db_name: str = Field(default="user_db", validation_alias=AliasChoices("USER_DB_NAME"))
    # Runtime user: SELECT/INSERT/UPDATE/DELETE on user_db only. Used by the running service.
    db_user: str = Field(default="user_svc", validation_alias=AliasChoices("USER_DB_USER"))
    db_password: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("USER_DB_PASSWORD")
    )
    # Migration user: DDL on user_db only. Used by Alembic, never by the running service.
    db_migration_user: str = Field(
        default="user_migrator", validation_alias=AliasChoices("USER_DB_MIGRATION_USER")
    )
    db_migration_password: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("USER_DB_MIGRATION_PASSWORD")
    )
    db_connect_timeout_seconds: int = Field(
        default=3, validation_alias=AliasChoices("DB_CONNECT_TIMEOUT_SECONDS")
    )
    db_pool_size: int = Field(default=5, validation_alias=AliasChoices("DB_POOL_SIZE"))

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
                "USER_DB_MIGRATION_USER and USER_DB_MIGRATION_PASSWORD must be set to run migrations."
            )
        return self._url(self.db_migration_user, self.db_migration_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()
