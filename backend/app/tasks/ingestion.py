import asyncio

from app.ingestion.watcher import poll_watch_root_once
from app.tasks.celery_app import celery_app
from app.tasks.db import task_db_session


@celery_app.task(name="app.tasks.ingestion.poll_watch_root")
def poll_watch_root() -> dict[str, object] | None:
    """Celery beat entry point for watch mode (FR-03). Celery tasks are synchronous, so this
    just runs the async ingestion service in a fresh event loop.
    """
    return asyncio.run(_poll_watch_root_async())


async def _poll_watch_root_async() -> dict[str, object] | None:
    async with task_db_session() as db:
        summary = await poll_watch_root_once(db)
        return summary.model_dump(mode="json") if summary else None
