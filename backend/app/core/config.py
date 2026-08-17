from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, sourced from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "PCB-Inspect"
    environment: str = "development"
    secret_key: str = Field(default="dev-secret-change-me")

    # Language a station starts in, before anyone picks one in Settings (issue #50). Only the
    # *initial* value: once `ui_language` is set in `SystemConfig` it wins, same as every other
    # runtime setting (FR-13).
    default_language: Literal["en", "pt"] = "en"

    # Database
    database_url: str = "postgresql+asyncpg://pcb_inspect:pcb_inspect@db:5432/pcb_inspect"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Storage — the watch root is read-only (section 3.5/14.1 of the PRD); app_data is writable
    watch_root: Path = Path("/data/watch-root")
    app_data_dir: Path = Path("/data/app-data")

    # Host filesystem, bind-mounted read-only so the operator can point the watch root at any
    # folder on their machine from the UI instead of editing .env and restarting the stack
    # (FR-20). `host_fs_root` is the host directory that was mounted and `host_fs_mount` is
    # where it lands inside the container — together they let `app.core.host_paths` translate
    # an operator-entered host path into something the container can actually open. Set
    # `host_fs_mount` to "" when the app runs directly on the host, with no translation needed.
    host_fs_root: str = "/"
    host_fs_mount: str = "/hostfs"

    # Inference backend (RV-01/RV-02). "fake" swaps the loaded model for a deterministic
    # stub (app/inference/model.py) — used only by the Playwright E2E job (section 14.2),
    # since `weights/best.pt` (114MB, README) isn't tracked in git and CI runners have no
    # GPU. Never set outside that job; the default drives every real deployment.
    inference_backend: Literal["ultralytics", "fake"] = "ultralytics"

    # LLM (section 5.2 — local-first by default)
    llm_provider: str = "openai_compatible"
    llm_base_url: str = "http://host.docker.internal:1234/v1"
    llm_model: str = "local-model"
    llm_api_key: str | None = None
    llm_timeout_s: int = 60
    # Passed through as `reasoning_effort` when set, and omitted entirely when not, so an
    # endpoint that has never heard of the field is unaffected. It exists because reasoning
    # models are not interchangeable with plain ones under forced JSON output: Groq's
    # `qwen/qwen3.6-27b` fails *every* `response_format: json_object` call with
    # `json_validate_failed` and an empty generation until reasoning is turned off, while
    # `openai/gpt-oss-120b` on the same provider is fine with it left on. Which value is right
    # is a property of the model, so it is resolved per role alongside the model name.
    llm_reasoning_effort: str | None = None

    # Per-role overrides (`app.agents.llm_client.LLMRole`). The three tiers ask very different
    # things of a model — the chat wants first-token latency, the report wants long-form
    # synthesis, the analysis chain wants structured-output discipline — and they don't have to
    # come from one endpoint any more: each role carries its own base_url/model/api_key, and
    # every field left unset falls back to the `llm_*` value above, so a single-endpoint
    # station keeps working with nothing but the globals set.
    llm_chat_base_url: str | None = None
    llm_chat_model: str | None = None
    llm_chat_api_key: str | None = None
    llm_chat_reasoning_effort: str | None = None
    llm_analysis_base_url: str | None = None
    llm_analysis_model: str | None = None
    llm_analysis_api_key: str | None = None
    llm_analysis_reasoning_effort: str | None = None
    llm_report_base_url: str | None = None
    llm_report_model: str | None = None
    llm_report_api_key: str | None = None
    llm_report_reasoning_effort: str | None = None
    # Caps a single completion's generated tokens. A local CPU model writes a few tokens per
    # second, so an unbounded answer is what turns a chat reply into a multi-minute wait;
    # 800 is comfortably more than any answer this assistant needs to give.
    llm_max_tokens: int = 800

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

    @property
    def golden_set_dir(self) -> Path:
        """Versioned local reference set for golden-set evaluation (FR-12) — alongside
        app-data, never the (read-only) watch root, so the evaluation job can be pointed at
        it without needing a dedicated compose volume.
        """
        return self.app_data_dir / "golden-set"

    @property
    def uploaded_weights_dir(self) -> Path:
        """Where weight files uploaded from Settings > Models are stored (FR-12). Under
        app-data because that is the one volume the API and the workers share read-write —
        `/weights` is a read-only bind mount of the repo's own `weights/` directory, and the
        file has to outlive whatever folder the operator downloaded it into.
        """
        return self.app_data_dir / "weights"


@lru_cache
def get_settings() -> Settings:
    return Settings()
