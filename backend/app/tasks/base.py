import asyncio
import uuid
from typing import Any

from celery import Task

from app.inspections.state import mark_failed
from app.models import InspectionImage
from app.tasks.db import task_db_session
from app.tasks.errors import TransientProcessingError


class PipelineTask(Task):  # type: ignore[misc]  # celery.Task ships no type stubs
    """Base for stage tasks in the QUEUED -> ... -> COMPLETED | FAILED pipeline (FR-04).

    - `acks_late`/`reject_on_worker_lost` (NFR-03): a task in progress when its worker is
      killed returns to the queue instead of being lost.
    - `autoretry_for` retries `TransientProcessingError` up to `max_retries` times with
      exponential backoff (section 3.7); any other exception fails the task immediately.
    - `on_failure` fires once retries are exhausted (or immediately for a non-transient
      error) and persists `FAILED` + the reason — it never touches the original file
      (section 3.5), only the database row.
    """

    autoretry_for = (TransientProcessingError,)
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True
    max_retries = 3
    acks_late = True
    reject_on_worker_lost = True

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        inspection_image_id = args[0] if args else kwargs.get("inspection_image_id")
        if inspection_image_id is None:
            return
        asyncio.run(_mark_failed_async(str(inspection_image_id), str(exc)))


async def _mark_failed_async(inspection_image_id: str, reason: str) -> None:
    async with task_db_session() as db:
        image = await db.get(InspectionImage, uuid.UUID(inspection_image_id))
        if image is None:
            return
        mark_failed(image, reason)
        await db.commit()
