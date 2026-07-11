import asyncio
import logging
import os
import uuid

from celery.signals import worker_ready

from app.core.config import get_settings
from app.inference.model import ensure_model_loaded
from app.inference.service import process_image
from app.inspections.state import transition
from app.models import InspectionImage
from app.models.enums import ImageStatus
from app.tasks.base import PipelineTask
from app.tasks.celery_app import celery_app
from app.tasks.db import task_db_session

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, base=PipelineTask, name="app.tasks.pipeline.run_inference")
def run_inference(self: PipelineTask, inspection_image_id: str) -> None:
    """Entry point enqueued on ingestion (FR-04). Moves the image to `PROCESSING`, then runs
    YOLO detection (FR-05): persists detections, generates the annotated image, and
    transitions to `DETECTED` (reportable defect found) or straight to `COMPLETED` (FR-05's
    no-defect path).
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

        if image.status is not ImageStatus.PROCESSING:
            # Already advanced past this stage by a prior (redelivered) attempt — rerunning
            # detection here would duplicate Detection rows.
            return

        loaded = await ensure_model_loaded()
        await process_image(db, image, loaded, app_data_dir=get_settings().app_data_dir)
        await db.commit()


@worker_ready.connect
def _warm_start_inference_worker(**kwargs: object) -> None:
    """Eager warm start (RV-01) for the dedicated inference worker only — `celery_app`'s
    `include` list is imported by every worker process (inference, agents) and by `beat`, so
    this is gated on `WORKER_ROLE` (set per-service in docker-compose.yml) to avoid loading
    YOLO weights into the agent worker, which has no GPU and never runs detection.

    Best-effort: a failure here (DB not migrated/seeded yet, weights missing) is logged, not
    raised — it would otherwise crash the whole worker process before it can consume a
    single task. The first `run_inference` task still loads the model itself (idempotently)
    if this warm-up didn't already succeed.
    """
    if os.environ.get("WORKER_ROLE") != "inference":
        return
    try:
        asyncio.run(ensure_model_loaded())
    except Exception:
        logger.warning(
            "Warm-start model load failed at worker boot; will retry on first task",
            exc_info=True,
        )


@celery_app.task(bind=True, base=PipelineTask, name="app.tasks.pipeline.run_agent_analysis")
def run_agent_analysis(self: PipelineTask, inspection_image_id: str) -> None:
    """No-op skeleton; the Analyst/Reviewer/Summarizer chain lands in Issue 7."""
