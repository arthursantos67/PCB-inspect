import asyncio
import logging
import os
import uuid

from celery.signals import worker_ready

from app.analyses.service import create_baseline_analysis
from app.core.config import get_settings
from app.events.publisher import publish_event
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
    no-defect path). When a reportable detection is found, immediately follows up with the
    knowledge-base baseline analysis (FR-06, Issue 7), which is what takes the image the
    rest of the way from `DETECTED` to `COMPLETED` — there's no agent chain yet to justify
    an `ANALYZING` stopover.
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
        reportable_detections = await process_image(
            db, image, loaded, app_data_dir=get_settings().app_data_dir
        )
        # Non-empty exactly when `process_image` transitioned the image to `DETECTED`
        # (empty otherwise, per its own contract) — checking this instead of re-reading
        # `image.status` also sidesteps a stale mypy literal-narrowing false positive from
        # the `PROCESSING` guard above, which a call into another function can't invalidate.
        analysis = None
        if reportable_detections:
            analysis = await create_baseline_analysis(db, image, reportable_detections)
        await db.commit()

        # Published only after commit (FR-14): a listening client must never observe an
        # event for a row it can't yet read back.
        await publish_event(
            "detection.completed", {"id": str(image.id), "status": image.status.value}
        )
        if analysis is not None:
            await publish_event(
                "analysis.completed",
                {
                    "id": str(image.id),
                    "status": image.status.value,
                    "analysis_id": str(analysis.id),
                },
            )


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
    """No-op skeleton; the Analyst/Reviewer/Summarizer chain (FR-06's conditional tier,
    Phase 2) lands in a later issue."""
