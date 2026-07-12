"""Baseline analysis generation (FR-06's baseline tier, Issue 7): synchronous, LLM-free,
always available.

Called immediately after the inference stage (`app.inference.service.process_image`)
reaches `DETECTED` — knowledge-base lookups are pure in-memory dict access, so this adds no
perceptible latency to the main flow (NFR-01). Enriching this into an agent-generated
analysis (`analysis_source = agents`) is FR-06's conditional tier (Phase 2) and out of
scope here; this always runs first and is what a from-scratch inspection ends up with when
no agent chain runs.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.inspections.state import transition
from app.knowledge.defects import DEFECT_KNOWLEDGE_BASE
from app.models import Analysis, Detection, InspectionImage
from app.models.enums import AnalysisSource, AnalysisStatus, ImageStatus, Severity, severity_rank


def compute_severity_max(detections: Sequence[Detection]) -> Severity:
    """The highest knowledge-base severity among `detections` — shared by the baseline
    analysis and the agent trigger policy's "baseline severity >= high" condition
    (`app.agents.policy`), so both read the exact same in-memory lookup.
    """
    return max(
        (DEFECT_KNOWLEDGE_BASE[d.defect_type].severity for d in detections),
        key=severity_rank,
    )


async def create_baseline_analysis(
    db: AsyncSession,
    image: InspectionImage,
    reportable_detections: Sequence[Detection],
    *,
    transition_to: ImageStatus = ImageStatus.COMPLETED,
) -> Analysis:
    """Creates the 1:1 `Analysis` (RN-03) for `image` from the static knowledge base.
    `reportable_detections` must be non-empty (the no-defect path, FR-05, never reaches
    `DETECTED` and so never calls this).

    `transition_to` defaults to `COMPLETED` — baseline-only skips `ANALYZING` (FR-06/FR-04)
    since no agent chain runs. The pipeline (`app.tasks.pipeline`) passes `ANALYZING` instead
    when the `agent_analysis_mode` policy (issue #31) decides the Analyst/Reviewer/Summarizer
    chain should run next, so the image doesn't prematurely land on a terminal status.
    """
    per_defect = []
    for detection in reportable_detections:
        entry = DEFECT_KNOWLEDGE_BASE[detection.defect_type]
        per_defect.append(
            {
                "detection_id": str(detection.id),
                "description": entry.description,
                "probable_causes": list(entry.probable_causes),
                "suggested_solutions": list(entry.suggested_solutions),
                "severity": entry.severity.value,
            }
        )

    analysis = Analysis(
        image_id=image.id,
        status=AnalysisStatus.COMPLETED,
        source=AnalysisSource.KNOWLEDGE_BASE,
        per_defect=per_defect,
        severity_max=compute_severity_max(reportable_detections),
    )
    db.add(analysis)
    transition(image, transition_to)
    return analysis


async def get_analysis(db: AsyncSession, analysis_id: uuid.UUID) -> Analysis:
    analysis = await db.get(Analysis, analysis_id)
    if analysis is None:
        raise ApiError("RESOURCE_NOT_FOUND", "Analysis not found.", 404)
    return analysis
