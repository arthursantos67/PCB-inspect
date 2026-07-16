import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.detections import service
from app.detections.schemas import DetectionFeedbackOut, DetectionFeedbackRequest
from app.models import User

router = APIRouter(prefix="/api/v1/detections", tags=["detections"])


@router.post("/{detection_id}/feedback", response_model=DetectionFeedbackOut)
async def submit_detection_feedback(
    detection_id: uuid.UUID,
    payload: DetectionFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DetectionFeedbackOut:
    """Mark a detection `confirmed`/`false_positive` (FR-10) — independently of the
    analysis-level review. Audited (FR-16) and feeds dataset export (FR-18).
    """
    detection = await service.set_detection_review(
        db, actor_id=current_user.id, detection_id=detection_id, review=payload.review
    )
    return DetectionFeedbackOut.model_validate(detection)
