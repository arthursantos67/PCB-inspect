import uuid
from datetime import datetime

from pydantic import BaseModel

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
