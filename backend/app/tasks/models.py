"""Golden-set evaluation and the no-downtime activation reload (FR-12). Each task drives its
own throwaway `asyncio.run()` loop, same as `app.tasks.pipeline` — not the FastAPI app's
long-lived loop (see `app.tasks.db.task_db_session`).

Both tasks are routed to the `inference` queue (`app.tasks.celery_app`), consumed by the same
single-process, `--pool=solo` worker that runs `run_inference` — this is what makes the
no-downtime activation switch actually safe: with concurrency 1, a queued `reload_inference_model`
task can only ever execute strictly before or after an in-flight `run_inference` task, never
interleaved with one, so activating a new version never interrupts a detection already running
(FR-12's "No-Downtime Switch" acceptance criterion). It also serializes evaluation with real
production inference on the one available GPU, rather than contending for it.
"""

import asyncio
import logging
import uuid

from app.audit.service import record_audit
from app.core.config import get_settings
from app.core.errors import ApiError
from app.inference import golden_set
from app.inference.model import reload_active_model
from app.models import ModelVersion
from app.models.enums import ModelEvaluationStatus
from app.tasks.celery_app import celery_app
from app.tasks.db import task_db_session

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.models.run_model_evaluation")
def run_model_evaluation(model_version_id: str) -> None:
    """Enqueued right after a new `ModelVersion` is registered (`app.settings.models_router`).
    Always runs the real golden-set evaluation (RN-10) — `ModelVersion.metrics` has no other
    writer anywhere in the codebase.
    """
    asyncio.run(_run_model_evaluation_async(model_version_id))


async def _run_model_evaluation_async(model_version_id: str) -> None:
    version_uuid = uuid.UUID(model_version_id)

    async with task_db_session() as db:
        model_version = await db.get(ModelVersion, version_uuid)
        if model_version is None:
            return
        weights_path = model_version.weights_path
        model_version.evaluation_status = ModelEvaluationStatus.RUNNING
        model_version.evaluation_error = None
        await db.commit()

    try:
        manifest = golden_set.load_manifest(get_settings().golden_set_dir)
        # `evaluate_weights` is a blocking, CPU/GPU-bound call (model load + inference over
        # every golden-set image) — offloaded to a thread so it never blocks this task's
        # event loop the way a stray awaited I/O call would.
        metrics = await asyncio.to_thread(golden_set.evaluate_weights, weights_path, manifest)
    except Exception as exc:  # noqa: BLE001 — a bad golden set/weights file must never crash
        # the worker; it degrades to a FAILED evaluation the operator can see and re-trigger.
        reason = exc.message if isinstance(exc, ApiError) else str(exc)
        logger.warning(
            "Golden-set evaluation failed for model_version_id=%s: %s", model_version_id, reason
        )
        async with task_db_session() as db:
            model_version = await db.get(ModelVersion, version_uuid)
            if model_version is None:
                return
            model_version.evaluation_status = ModelEvaluationStatus.FAILED
            model_version.evaluation_error = reason
            await record_audit(
                db,
                actor_id=None,
                action="model.evaluation_failed",
                entity_type="model_version",
                entity_id=version_uuid,
                payload={"reason": reason},
            )
            await db.commit()
        return

    async with task_db_session() as db:
        model_version = await db.get(ModelVersion, version_uuid)
        if model_version is None:
            return
        model_version.evaluation_status = ModelEvaluationStatus.COMPLETED
        model_version.evaluation_error = None
        model_version.metrics = {
            "map50": metrics.map50,
            "map50_95": metrics.map50_95,
            "per_class": metrics.per_class,
            "golden_set_version": metrics.golden_set_version,
            "image_count": metrics.image_count,
        }
        await record_audit(
            db,
            actor_id=None,
            action="model.evaluated",
            entity_type="model_version",
            entity_id=version_uuid,
            payload={"map50": metrics.map50, "map50_95": metrics.map50_95},
        )
        await db.commit()


@celery_app.task(name="app.tasks.models.reload_inference_model")
def reload_inference_model() -> None:
    """Enqueued right after activation commits (`app.settings.models_router`) — swaps the
    warm-started model for the newly active version on the inference worker process. See the
    module docstring for why this can never interrupt an in-flight `run_inference` task.
    """
    asyncio.run(reload_active_model())
