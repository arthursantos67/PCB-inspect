import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import (
    AnalysisReviewAction,
    AnalysisReviewStatus,
    AnalysisSource,
    AnalysisStatus,
    DispositionRecommendation,
    Severity,
)


class PerDefectEntry(BaseModel):
    detection_id: uuid.UUID
    description: str
    probable_causes: list[str]
    suggested_solutions: list[str]
    severity: Severity


class AnalysisReviewOut(BaseModel):
    """One row of `Analysis.reviews` (FR-10, Issue 33) — the immutable validate/reject
    history, queryable independent of `Analysis.review_status`.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    reviewer_id: uuid.UUID
    action: AnalysisReviewAction
    comment: str | None
    created_at: datetime


class ReviewRequest(BaseModel):
    """`POST /api/v1/analyses/{id}/review` body (FR-10, UC-8)."""

    action: AnalysisReviewAction
    comment: str | None = None


class AnalysisOut(BaseModel):
    """Shape matches PRD section 11.5's embedded `analysis` example, plus `reviews` (FR-10,
    Issue 33's "queryable later" acceptance criterion).
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    image_id: uuid.UUID
    status: AnalysisStatus
    source: AnalysisSource
    severity_max: Severity | None
    disposition_recommendation: DispositionRecommendation | None
    executive_summary: str | None
    per_defect: list[PerDefectEntry] | None
    review_status: AnalysisReviewStatus
    reviews: list[AnalysisReviewOut] = []
    created_at: datetime
