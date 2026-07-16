import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, model_validator

from app.analyses.schemas import AnalysisOut
from app.models.enums import (
    AnalysisReviewStatus,
    BoardDispositionDecision,
    DefectType,
    DetectionReview,
    DetectionSource,
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
    disposition: BoardDispositionDecision | None
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
    model_version: str | None
    review: DetectionReview
    source: DetectionSource


class InspectionBoard(BaseModel):
    board_number: str | None
    batch_number: str | None


class BBoxIn(BaseModel):
    """A manually-drawn bbox (FR-10) — normalized [0,1], `x1<x2`/`y1<y2` (mirrors the
    `detection.bbox_normalized_and_ordered` DB check constraint, RN-01), validated here so a
    malformed box is rejected as `VALIDATION_FAILED` rather than surfacing as a raw
    `IntegrityError`.
    """

    x1: float
    y1: float
    x2: float
    y2: float

    @model_validator(mode="after")
    def _check_bounds(self) -> Self:
        for value in (self.x1, self.y1, self.x2, self.y2):
            if not 0.0 <= value <= 1.0:
                raise ValueError("bbox coordinates must be within [0, 1]")
        if self.x1 >= self.x2:
            raise ValueError("bbox x1 must be less than x2")
        if self.y1 >= self.y2:
            raise ValueError("bbox y1 must be less than y2")
        return self


class AnnotationRequest(BaseModel):
    """`POST /api/v1/inspections/{id}/annotations` body (FR-10) — a defect the model missed,
    drawn directly in the viewer.
    """

    defect_type: DefectType
    bbox: BBoxIn


class BoardDispositionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    image_id: uuid.UUID
    decision: BoardDispositionDecision
    decided_by: uuid.UUID
    created_at: datetime


class DispositionRequest(BaseModel):
    """`POST /api/v1/inspections/{id}/disposition` body (FR-10, UC-5)."""

    decision: BoardDispositionDecision


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
    disposition: BoardDispositionOut | None = None
