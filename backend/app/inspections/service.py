import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.core.errors import ApiError
from app.inspections.schemas import BBoxIn
from app.models import BoardDisposition, Detection, InspectionImage
from app.models.enums import BoardDispositionDecision, DefectType, DetectionReview, DetectionSource

# A manual annotation is a human-confirmed observation, not a model estimate — full
# confidence reflects that it isn't subject to the confidence thresholds in RV-03.
_MANUAL_CONFIDENCE = Decimal("1.000")


async def set_disposition(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID,
    image_id: uuid.UUID,
    decision: BoardDispositionDecision,
) -> BoardDisposition:
    """Records a board's final disposition (FR-10, UC-5) — one row per inspection (RN-09);
    a later change updates it in place, with the previous value captured in the audit
    payload (FR-16) rather than as a new `BoardDisposition` row.
    """
    image = await db.get(InspectionImage, image_id)
    if image is None:
        raise ApiError("INSPECTION_NOT_FOUND", "Inspection image not found.", 404)

    disposition = await db.scalar(
        select(BoardDisposition).where(BoardDisposition.image_id == image_id)
    )
    previous = disposition.decision if disposition is not None else None

    if disposition is None:
        disposition = BoardDisposition(image_id=image_id, decision=decision, decided_by=actor_id)
        db.add(disposition)
    else:
        disposition.decision = decision
        disposition.decided_by = actor_id
    await db.flush()

    await record_audit(
        db,
        actor_id=actor_id,
        action="board.disposition_set",
        entity_type="board_disposition",
        entity_id=disposition.id,
        payload={
            "decision": decision.value,
            "previous": previous.value if previous is not None else None,
        },
    )
    await db.commit()
    await db.refresh(disposition)
    return disposition


async def annotate_detection(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID,
    image_id: uuid.UUID,
    defect_type: DefectType,
    bbox: BBoxIn,
) -> Detection:
    """Manually annotates a defect the model missed (FR-10) — creates a `Detection` row
    flagged `source=manual`, distinguishable from model output in the UI and in dataset
    exports (FR-18). Pre-confirmed (`review=confirmed`): the operator drawing it *is* the
    confirmation, there is no model output left to confirm/reject against. Audited (FR-16).
    """
    image = await db.get(InspectionImage, image_id)
    if image is None:
        raise ApiError("INSPECTION_NOT_FOUND", "Inspection image not found.", 404)

    detection = Detection(
        image_id=image_id,
        defect_type=defect_type,
        bbox=bbox.model_dump(),
        confidence=_MANUAL_CONFIDENCE,
        is_reported=True,
        model_version_id=None,
        source=DetectionSource.MANUAL,
        review=DetectionReview.CONFIRMED,
        reviewed_by=actor_id,
    )
    db.add(detection)
    await db.flush()

    await record_audit(
        db,
        actor_id=actor_id,
        action="detection.annotated",
        entity_type="detection",
        entity_id=detection.id,
        payload={
            "image_id": str(image_id),
            "defect_type": defect_type.value,
            "bbox": bbox.model_dump(),
        },
    )
    await db.commit()
    await db.refresh(detection)
    return detection
