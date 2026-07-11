import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import (
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


class AnalysisOut(BaseModel):
    """Shape matches PRD section 11.5's embedded `analysis` example."""

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
    created_at: datetime
