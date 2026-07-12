import asyncio
import os
from typing import Literal

import httpx
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import Settings
from app.inference.status import get_model_status

# Independent of the configured `llm.timeout_s` (which bounds an actual inference call, up to
# 60s by default) — a health probe must stay fast even when the provider is slow/unresponsive.
_LLM_PROBE_TIMEOUT_S = 5.0

Status = Literal["ok", "error", "not_configured"]

# Mirrors the `--queues` each worker service in docker-compose.yml consumes — if any of these
# has no worker responding, ingestion/alerting/retention or agent analysis has silently
# stopped even though at least one worker (e.g. inference) is still up.
_EXPECTED_QUEUES = {"inference", "agents", "housekeeping"}


class CheckResult(BaseModel):
    status: Status
    detail: str | None = None


class WorkerCheckResult(CheckResult):
    """Adds the inference worker's warm-start state (RV-01/RV-02) on top of the plain
    reachability check every other component reports.
    """

    model_loaded: bool = False
    device: str | None = None
    model_version: str | None = None


class HealthReport(BaseModel):
    status: Literal["ok", "degraded"]
    db: CheckResult
    redis: CheckResult
    worker: WorkerCheckResult
    watch_root: CheckResult
    llm: CheckResult


async def check_db(settings: Settings) -> CheckResult:
    try:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return CheckResult(status="ok")
    except Exception as exc:  # noqa: BLE001 — health check must never raise
        return CheckResult(status="error", detail=str(exc))


async def check_redis(settings: Settings) -> CheckResult:
    client: Redis | None = None
    try:
        client = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        await client.ping()
        return CheckResult(status="ok")
    except Exception as exc:  # noqa: BLE001
        return CheckResult(status="error", detail=str(exc))
    finally:
        if client is not None:
            await client.aclose()


async def check_worker(settings: Settings) -> WorkerCheckResult:
    """Inspects which queues have a Celery worker actively consuming them, then enriches the
    result with the inference worker's warm-start state (RV-01/RV-02) published to Redis by
    `app.inference.model.ensure_model_loaded`.

    A plain `control.ping()` only tells us *some* worker replied — with `worker-agents` dead
    and only `worker-inference` up, that still returns a non-empty reply and would report
    "ok" while ingestion/alerting/retention/agent analysis have all silently stopped. Checking
    each expected queue's `active_queues()` membership instead catches that partial outage.
    """
    try:
        from app.tasks.celery_app import celery_app

        active_queues = await asyncio.to_thread(
            celery_app.control.inspect(timeout=1.0).active_queues
        )
    except Exception as exc:  # noqa: BLE001
        return WorkerCheckResult(status="error", detail=str(exc))

    if not active_queues:
        return WorkerCheckResult(status="error", detail="no worker responded")

    responding_queues = {
        queue["name"] for queues in active_queues.values() for queue in (queues or [])
    }
    missing = _EXPECTED_QUEUES - responding_queues

    model_status = await get_model_status(settings)
    model_loaded = False if model_status is None else model_status["model_loaded"]
    device = None if model_status is None else model_status["device"]
    model_version = None if model_status is None else model_status["model_version"]

    if missing:
        return WorkerCheckResult(
            status="error",
            detail=f"no worker consuming queue(s): {', '.join(sorted(missing))}",
            model_loaded=model_loaded,
            device=device,
            model_version=model_version,
        )
    return WorkerCheckResult(
        status="ok",
        detail=f"{len(active_queues)} worker(s) responding, all queues covered",
        model_loaded=model_loaded,
        device=device,
        model_version=model_version,
    )


async def check_watch_root(settings: Settings) -> CheckResult:
    path = settings.watch_root
    if not path.exists():
        return CheckResult(status="error", detail=f"{path} does not exist")
    if not os.access(path, os.R_OK):
        return CheckResult(status="error", detail=f"{path} is not readable")
    return CheckResult(status="ok", detail=str(path))


def _llm_probe_request(
    provider: str, base_url: str, api_key: str | None
) -> tuple[str, dict[str, str]]:
    """Returns the (url, headers) of a lightweight, read-only "list models" call for each
    supported provider (section 5.2) — enough to prove the endpoint and credential are live
    without spending a real generation call.
    """
    if provider == "openai_compatible":
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        return f"{base_url.rstrip('/')}/models", headers
    if provider == "anthropic":
        headers = {"x-api-key": api_key or "", "anthropic-version": "2023-06-01"}
        return "https://api.anthropic.com/v1/models", headers
    if provider == "google":
        return f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}", {}
    raise ValueError(f"unknown provider: {provider}")


async def check_llm(settings: Settings, db: AsyncSession) -> CheckResult:
    """Pings the configured provider's model-listing endpoint (section 5.2) and reports actual
    reachability — `openai_compatible` (local LM Studio/Ollama/vLLM by default) always has a
    target URL, so it's only ever `ok`/`error`; the cloud providers additionally need an API
    key opted in, so they report `not_configured` until one is set.
    """
    from app.settings.service import get_config_value, get_secret_config_value

    provider = await get_config_value(db, "llm.provider", settings.llm_provider)
    model = await get_config_value(db, "llm.model", settings.llm_model)
    base_url = await get_config_value(db, "llm.base_url", settings.llm_base_url)
    api_key = await get_secret_config_value(db, "llm.api_key") or settings.llm_api_key

    if provider in ("anthropic", "google") and not api_key:
        return CheckResult(
            status="not_configured", detail=f"provider={provider}: no API key configured"
        )

    try:
        url, headers = _llm_probe_request(provider, base_url, api_key)
    except ValueError as exc:
        return CheckResult(status="error", detail=str(exc))

    try:
        async with httpx.AsyncClient(timeout=_LLM_PROBE_TIMEOUT_S) as http_client:
            response = await http_client.get(url, headers=headers)
        if response.status_code >= 400:
            return CheckResult(
                status="error",
                detail=f"provider={provider} model={model} http_status={response.status_code}",
            )
        return CheckResult(status="ok", detail=f"provider={provider} model={model} reachable")
    except httpx.HTTPError as exc:
        return CheckResult(
            status="error", detail=f"provider={provider} model={model} unreachable: {exc}"
        )


async def build_health_report(settings: Settings, db: AsyncSession) -> HealthReport:
    db_check, redis, worker, watch_root, llm = await asyncio.gather(
        check_db(settings),
        check_redis(settings),
        check_worker(settings),
        check_watch_root(settings),
        check_llm(settings, db),
    )
    checks = (db_check, redis, worker, watch_root, llm)
    overall = "ok" if all(c.status in ("ok", "not_configured") for c in checks) else "degraded"
    return HealthReport(
        status=overall, db=db_check, redis=redis, worker=worker, watch_root=watch_root, llm=llm
    )
