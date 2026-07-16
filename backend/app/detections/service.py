import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.core.errors import ApiError
from app.models import Detection
from app.models.enums import DetectionReview


async def set_detection_review(
    db: AsyncSession, *, actor_id: uuid.UUID, detection_id: uuid.UUID, review: DetectionReview
) -> Detection:
    """Per-detection feedback (FR-10) — independent of the analysis-level review
    (`app.analyses.service.review_analysis`): an operator can confirm/reject individual
    bounding boxes regardless of whether the analysis itself was validated or rejected.
    Audited per FR-16.
    """
    detection = await db.get(Detection, detection_id)
    if detection is None:
        raise ApiError("RESOURCE_NOT_FOUND", "Detection not found.", 404)

    previous = detection.review
    detection.review = review
    detection.reviewed_by = actor_id
    await db.flush()

    await record_audit(
        db,
        actor_id=actor_id,
        action="detection.reviewed",
        entity_type="detection",
        entity_id=detection.id,
        payload={"review": review.value, "previous": previous.value},
    )
    await db.commit()
    await db.refresh(detection)
    return detection
