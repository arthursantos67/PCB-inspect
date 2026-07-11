import asyncio
import os
from typing import Literal

from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.inference.status import get_model_status

Status = Literal["ok", "error", "not_configured"]


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
    """Pings Celery workers, then enriches the result with the inference worker's warm-start
    state (RV-01/RV-02) published to Redis by `app.inference.model.ensure_model_loaded`.
    """
    try:
        from app.tasks.celery_app import celery_app

        replies = await asyncio.to_thread(celery_app.control.ping, timeout=1.0)
        if not replies:
            return WorkerCheckResult(status="error", detail="no worker responded")
    except Exception as exc:  # noqa: BLE001
        return WorkerCheckResult(status="error", detail=str(exc))

    model_status = await get_model_status(settings)
    if model_status is None:
        return WorkerCheckResult(
            status="ok", detail=f"{len(replies)} worker(s) responding", model_loaded=False
        )
    return WorkerCheckResult(
        status="ok",
        detail=f"{len(replies)} worker(s) responding",
        model_loaded=model_status["model_loaded"],
        device=model_status["device"],
        model_version=model_status["model_version"],
    )


async def check_watch_root(settings: Settings) -> CheckResult:
    path = settings.watch_root
    if not path.exists():
        return CheckResult(status="error", detail=f"{path} does not exist")
    if not os.access(path, os.R_OK):
        return CheckResult(status="error", detail=f"{path} is not readable")
    return CheckResult(status="ok", detail=str(path))


async def check_llm(settings: Settings) -> CheckResult:
    """Stub for now — real reachability probing lands with the agent pipeline (FR-06)."""
    if not settings.llm_base_url and not settings.llm_api_key:
        return CheckResult(status="not_configured")
    return CheckResult(status="ok", detail=f"provider={settings.llm_provider} (unverified)")


async def build_health_report(settings: Settings) -> HealthReport:
    db, redis, worker, watch_root, llm = await asyncio.gather(
        check_db(settings),
        check_redis(settings),
        check_worker(settings),
        check_watch_root(settings),
        check_llm(settings),
    )
    checks = (db, redis, worker, watch_root, llm)
    overall = "ok" if all(c.status in ("ok", "not_configured") for c in checks) else "degraded"
    return HealthReport(
        status=overall, db=db, redis=redis, worker=worker, watch_root=watch_root, llm=llm
    )
