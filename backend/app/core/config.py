from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, sourced from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "PCB-Inspect"
    environment: str = "development"
    secret_key: str = Field(default="dev-secret-change-me")

    # Database
    database_url: str = "postgresql+asyncpg://pcb_inspect:pcb_inspect@db:5432/pcb_inspect"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Storage — the watch root is read-only (section 3.5/14.1 of the PRD); app_data is writable
    watch_root: Path = Path("/data/watch-root")
    app_data_dir: Path = Path("/data/app-data")

    # LLM (section 5.2 — local-first by default)
    llm_provider: str = "openai_compatible"
    llm_base_url: str = "http://host.docker.internal:1234/v1"
    llm_model: str = "local-model"
    llm_api_key: str | None = None
    llm_timeout_s: int = 60

    # Celery
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/1"

    # Auth (section 13) — short-lived access token with refresh; progressive lockout.
    access_token_expire_minutes: int = 15
    refresh_token_expire_minutes: int = 60 * 24 * 7
    max_failed_login_attempts: int = 5
    lockout_base_seconds: int = 60
    lockout_max_seconds: int = 30 * 60

    # CORS — the frontend is a separate origin (different port) even though both are
    # localhost-only (section 13); comma-separated list of allowed origins.
    cors_allow_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
