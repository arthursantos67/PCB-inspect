import asyncio

from app.db.session import AsyncSessionLocal
from app.ingestion.watcher import poll_watch_root_once
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.ingestion.poll_watch_root")
def poll_watch_root() -> dict[str, object] | None:
    """Celery beat entry point for watch mode (FR-03). Celery tasks are synchronous, so this
    just runs the async ingestion service in a fresh event loop.
    """
    return asyncio.run(_poll_watch_root_async())


async def _poll_watch_root_async() -> dict[str, object] | None:
    async with AsyncSessionLocal() as db:
        summary = await poll_watch_root_once(db)
        return summary.model_dump(mode="json") if summary else None
