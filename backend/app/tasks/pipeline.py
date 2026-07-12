import asyncio
import logging
import os
import uuid

from celery.signals import worker_ready
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.chain import run_chain
from app.agents.errors import AgentChainAbortedError
from app.agents.llm_client import build_llm_client
from app.agents.policy import evaluate_trigger, load_policy_config
from app.analyses.service import compute_severity_max, create_baseline_analysis
from app.core.config import get_settings
from app.events.publisher import publish_event
from app.inference.model import ensure_model_loaded
from app.inference.service import process_image
from app.inspections.state import transition
from app.models import Analysis, Batch, Board, Detection, InspectionImage
from app.models.enums import AnalysisSource, ImageStatus
from app.stats.cache import invalidate_all as invalidate_stats_cache
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
    knowledge-base baseline analysis (FR-06, Issue 7) and evaluates the `agent_analysis_mode`
    trigger policy (FR-06's agents tier, Issue 31): if it triggers, the image moves to
    `ANALYZING` instead of `COMPLETED` and `run_agent_analysis` is enqueued to take it the
    rest of the way; otherwise the baseline alone takes it straight to `COMPLETED`.
    """
    asyncio.run(_run_inference_async(inspection_image_id))


async def _load_board_context(
    db: AsyncSession, image: InspectionImage
) -> tuple[str | None, str | None]:
    """`(board_number, batch_number)` for prompt context — best-effort, `None` when the image
    has no linked board (e.g. an ad hoc import that was never matched to one, FR-03).
    """
    if image.board_id is None:
        return None, None
    row = (
        await db.execute(
            select(Board.board_number, Batch.batch_number)
            .select_from(Board)
            .outerjoin(Batch, Board.batch_id == Batch.id)
            .where(Board.id == image.board_id)
        )
    ).first()
    if row is None:
        return None, None
    return row[0], row[1]


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
        should_run_agents = False
        trigger_reason = ""
        if reportable_detections:
            policy_config = await load_policy_config(db)
            severity_max = compute_severity_max(reportable_detections)
            should_run_agents, trigger_reason = evaluate_trigger(
                policy_config, reportable_detections, severity_max
            )
            transition_to = ImageStatus.ANALYZING if should_run_agents else ImageStatus.COMPLETED
            analysis = await create_baseline_analysis(
                db, image, reportable_detections, transition_to=transition_to
            )
        await db.commit()

        # Every completed image changes the dashboard aggregates (FR-08) regardless of
        # whether it found a defect — invalidate ahead of the TTL so the SSE-triggered
        # refetch below doesn't serve a stale cached value (section 3.6).
        await invalidate_stats_cache()

        # Published only after commit (FR-14): a listening client must never observe an
        # event for a row it can't yet read back.
        await publish_event(
            "detection.completed", {"id": str(image.id), "status": image.status.value}
        )
        if analysis is not None:
            if should_run_agents:
                logger.info(
                    "Agent analysis triggered for image %s: %s", image.id, trigger_reason
                )
            else:
                # The baseline is the final analysis for this image — announce completion now.
                # When agents will run instead, `run_agent_analysis` publishes this event once
                # it (or its graceful fallback) reaches COMPLETED.
                await publish_event(
                    "analysis.completed",
                    {
                        "id": str(image.id),
                        "status": image.status.value,
                        "analysis_id": str(analysis.id),
                    },
                )

    if should_run_agents:
        # Enqueued after the transaction above commits (same rationale as ingestion's
        # enqueue-after-commit, section 3.5) and offloaded to a thread so the blocking Redis
        # publish call never stalls this task's event loop.
        await asyncio.to_thread(run_agent_analysis.delay, inspection_image_id)


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
    """Analyst -> Reviewer -> Summarizer chain (FR-06's agents tier, PRD 5.3, Issue 31).

    Enqueued either automatically (right after the baseline analysis commits, when the
    `agent_analysis_mode` policy triggers — `_run_inference_async`) or on demand (the
    `POST /api/v1/inspections/{id}/agent-analysis` endpoint). Either way the image must
    already be `ANALYZING` with a baseline `Analysis` row in place; anything else is treated
    as already handled by a prior/redelivered attempt and is a no-op (idempotent against
    Celery redelivery, mirroring `run_inference`).

    A misbehaving/unreachable LLM or an exhausted Reviewer reject/revise loop degrades
    gracefully: the baseline analysis is kept as-is (`analysis_source` stays
    `knowledge_base`) and the image still reaches `COMPLETED` — never a task failure (issue
    #31's "No LLM Configured => No Crash" and "Reviewer Loop Bounded" acceptance criteria).
    """
    asyncio.run(_run_agent_analysis_async(inspection_image_id))


async def _run_agent_analysis_async(inspection_image_id: str) -> None:
    async with task_db_session() as db:
        image = await db.get(InspectionImage, uuid.UUID(inspection_image_id))
        if image is None:
            return
        if image.status is not ImageStatus.ANALYZING:
            return

        analysis = await db.scalar(select(Analysis).where(Analysis.image_id == image.id))
        if analysis is None:
            # Shouldn't happen — the baseline analysis always precedes ANALYZING — but there's
            # nothing to enrich, so just let the image finish rather than getting stuck.
            transition(image, ImageStatus.COMPLETED)
            await db.commit()
            return

        detections = (
            (
                await db.execute(
                    select(Detection).where(
                        Detection.image_id == image.id, Detection.is_reported.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
        board_number, batch_number = await _load_board_context(db, image)

        fallback_reason: str | None = None
        client = await build_llm_client(db)
        if client is None:
            fallback_reason = "no LLM client configured for the current provider"
        else:
            policy_config = await load_policy_config(db)
            try:
                result = await run_chain(
                    client,
                    board_number=board_number,
                    batch_number=batch_number,
                    detections=detections,
                    max_review_attempts=policy_config.max_review_attempts,
                )
            except AgentChainAbortedError as exc:
                fallback_reason = str(exc)
            except Exception as exc:  # noqa: BLE001 — an LLM/agent bug must never fail the task
                logger.exception("Unexpected agent chain failure for image %s", image.id)
                fallback_reason = f"unexpected error: {exc}"
            else:
                analysis.source = AnalysisSource.AGENTS
                analysis.per_defect = result.per_defect
                analysis.executive_summary = result.executive_summary
                analysis.disposition_recommendation = result.disposition_recommendation
                analysis.severity_max = result.severity_max
                analysis.llm_provider = result.llm_provider
                analysis.llm_model = result.llm_model
                analysis.prompt_version = result.prompt_version
                analysis.tokens_used = result.tokens_used
                analysis.duration_ms = result.duration_ms

        if fallback_reason is not None:
            logger.warning(
                "Agent analysis degraded to baseline for image %s: %s",
                image.id,
                fallback_reason,
            )

        transition(image, ImageStatus.COMPLETED)
        await db.commit()

        await invalidate_stats_cache()
        await publish_event(
            "analysis.completed",
            {
                "id": str(image.id),
                "status": image.status.value,
                "analysis_id": str(analysis.id),
            },
        )
