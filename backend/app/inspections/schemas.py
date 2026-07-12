import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.analyses.schemas import AnalysisOut
from app.models.enums import (
    AnalysisReviewStatus,
    DefectType,
    DispositionRecommendation,
    ImageStatus,
    Severity,
)


class InspectionListItem(BaseModel):
    """One row of `GET /api/v1/inspections` (FR-07) — a summary shape for the search/history
    table and dashboard recent-analyses list (FE-02/FE-04), not the full detail (that stays
    on `GET /api/v1/inspections/{id}`, section 11.2).
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    status: ImageStatus
    batch_number: str | None
    board_number: str | None
    defect_types: list[DefectType]
    severity_max: Severity | None
    review_status: AnalysisReviewStatus | None
    disposition_recommendation: DispositionRecommendation | None
    failure_reason: str | None
    created_at: datetime
    processed_at: datetime | None


class PaginatedInspections(BaseModel):
    """Pagination envelope per PRD section 11.1."""

    count: int
    next: str | None
    previous: str | None
    results: list[InspectionListItem]


class DetectionOut(BaseModel):
    """One row of `InspectionDetail.detections` (FE-03, section 11.5). `model_version` is
    the version string (not the FK id) — what the viewer/detections panel actually display.
    Scoped to reportable detections (`is_reported=True`, RV-03) — the same rule that gates
    the dashboard/aggregates (RN-07) applies to what the operator sees on the detail screen.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    defect_type: DefectType
    bbox: dict[str, float]
    confidence: Decimal
    is_reported: bool
    model_version: str


class InspectionBoard(BaseModel):
    board_number: str | None
    batch_number: str | None


class AgentAnalysisRequested(BaseModel):
    """`POST /{inspection_id}/agent-analysis` (FE-03, `on_demand` mode, issue #31) response —
    the chain runs asynchronously on the `agents` queue, mirroring every other
    enqueue-and-202 endpoint in the API (section 11.1).
    """

    status: Literal["queued"] = "queued"


class InspectionDetail(BaseModel):
    """`GET /api/v1/inspections/{id}` (FE-03, section 11.5) — full detail for the analysis
    detail screen. Doubles as FR-04's progress-polling fallback to SSE: `detections` and
    `analysis` are simply empty/`None` until the pipeline reaches that stage.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    status: ImageStatus
    board: InspectionBoard
    failure_reason: str | None
    created_at: datetime
    processed_at: datetime | None
    duration_ms: int | None
    detections: list[DetectionOut]
    analysis: AnalysisOut | None = None
