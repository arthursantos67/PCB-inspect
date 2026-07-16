import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.models.enums import DefectType, DetectionReview, DetectionSource


class DetectionFeedbackRequest(BaseModel):
    """`POST /api/v1/detections/{id}/feedback` body (FR-10) — per-detection feedback is
    always an explicit human judgment call, so `unreviewed` (the pre-feedback default) is
    deliberately not an accepted value here.
    """

    review: Literal[DetectionReview.CONFIRMED, DetectionReview.FALSE_POSITIVE]


class DetectionFeedbackOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    image_id: uuid.UUID
    defect_type: DefectType
    confidence: Decimal
    is_reported: bool
    review: DetectionReview
    reviewed_by: uuid.UUID | None
    source: DetectionSource
