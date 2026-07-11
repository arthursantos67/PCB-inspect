import asyncio
import uuid

from app.inspections.state import transition
from app.models import InspectionImage
from app.models.enums import ImageStatus
from app.tasks.base import PipelineTask
from app.tasks.celery_app import celery_app
from app.tasks.db import task_db_session


@celery_app.task(bind=True, base=PipelineTask, name="app.tasks.pipeline.run_inference")
def run_inference(self: PipelineTask, inspection_image_id: str) -> None:
    """Entry point enqueued on ingestion (FR-04). Moves the image to `PROCESSING`; the
    actual YOLO detection body is a no-op here and lands in Issue 6.
    """
    asyncio.run(_run_inference_async(inspection_image_id))


async def _run_inference_async(inspection_image_id: str) -> None:
    async with task_db_session() as db:
        image = await db.get(InspectionImage, uuid.UUID(inspection_image_id))
        if image is None:
            return
        # Idempotent against redelivery (acks_late/reject_on_worker_lost, NFR-03): if a
        # previous attempt already committed this transition before its worker died, treat
        # PROCESSING as already reached rather than re-applying — QUEUED->PROCESSING is not
        # a valid self-transition, and would otherwise fail the retried task permanently.
        if image.status is ImageStatus.QUEUED:
            transition(image, ImageStatus.PROCESSING)
            await db.commit()


@celery_app.task(bind=True, base=PipelineTask, name="app.tasks.pipeline.run_agent_analysis")
def run_agent_analysis(self: PipelineTask, inspection_image_id: str) -> None:
    """No-op skeleton; the Analyst/Reviewer/Summarizer chain lands in Issue 7."""
