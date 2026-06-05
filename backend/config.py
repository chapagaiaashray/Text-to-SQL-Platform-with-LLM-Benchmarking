"""Central configuration. All settings come from environment variables
(loaded from .env in dev). Import the singleton `settings` everywhere."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- Postgres connection ----
    postgres_user: str = Field(default="postgres")
    postgres_password: str = Field(default="postgres")
    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)
    metadata_db: str = Field(default="metadata")
    spider_db: str = Field(default="spider")

    # ---- Read-only executor role (Week 3) ----
    query_executor_user: str = Field(default="query_executor")
    query_executor_password: str = Field(default="change_me_readonly")
    query_timeout_ms: int = Field(default=5000)

    # ---- LLM keys (Week 2) ----
    openai_api_key: str = Field(default="")
    anthropic_api_key: str = Field(default="")
    google_api_key: str = Field(default="")
    ollama_base_url: str = Field(default="http://localhost:11434")

    # ---- App ----
    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")

    # ---- Derived connection strings ----
    def _dsn(self, user: str, password: str, db: str) -> str:
        return (
            f"postgresql://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{db}"
        )

    @property
    def metadata_dsn(self) -> str:
        """Full read-write access to the metadata DB."""
        return self._dsn(self.postgres_user, self.postgres_password, self.metadata_db)

    @property
    def spider_admin_dsn(self) -> str:
        """Admin access to the spider DB (used by the loader to create schemas)."""
        return self._dsn(self.postgres_user, self.postgres_password, self.spider_db)

    @property
    def spider_readonly_dsn(self) -> str:
        """Read-only access used by the sandboxed executor (Week 3)."""
        return self._dsn(
            self.query_executor_user, self.query_executor_password, self.spider_db
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
