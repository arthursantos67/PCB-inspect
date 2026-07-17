import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyses import service as analyses_service
from app.analyses.schemas import AnalysisOut, AnalysisReviewOut
from app.audit.service import record_audit
from app.core.errors import ApiError
from app.inspections.filters import (
    InspectionFilters,
    Ordering,
    apply_filters,
    base_query,
    order_by_clauses,
)
from app.inspections.schemas import (
    BBoxIn,
    BoardDispositionOut,
    DetectionOut,
    InspectionBoard,
    InspectionDetail,
    InspectionListItem,
)
from app.models import (
    Analysis,
    Batch,
    Board,
    BoardDisposition,
    Detection,
    InspectionImage,
    ModelVersion,
)
from app.models.enums import BoardDispositionDecision, DefectType, DetectionReview, DetectionSource

# A manual annotation is a human-confirmed observation, not a model estimate — full
# confidence reflects that it isn't subject to the confidence thresholds in RV-03.
_MANUAL_CONFIDENCE = Decimal("1.000")


async def load_defect_types(
    db: AsyncSession, image_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[DefectType]]:
    """Only reported detections feed listings/aggregates (RN-07). Queried separately from the
    page (rather than joined into it) to avoid duplicating each image row per detection.
    """
    if not image_ids:
        return {}
    rows = (
        await db.execute(
            select(Detection.image_id, Detection.defect_type)
            .where(Detection.image_id.in_(image_ids), Detection.is_reported.is_(True))
            .distinct()
        )
    ).all()
    result: dict[uuid.UUID, list[DefectType]] = {}
    for image_id, defect_type in rows:
        result.setdefault(image_id, []).append(defect_type)
    return result


async def list_all_inspections(
    db: AsyncSession, filters: InspectionFilters, ordering: Ordering = "-created_at"
) -> list[InspectionListItem]:
    """Every inspection matching `filters`, unpaginated — used by consolidated report
    generation (FR-11, Issue 35) so its row count is guaranteed to match `GET
    /api/v1/inspections`'s paginated `count` for the same filters (same `base_query` +
    `apply_filters` as the listing endpoint, not a re-implementation that could drift).
    """
    stmt = apply_filters(
        base_query(InspectionImage, Board, Batch, Analysis, BoardDisposition), filters
    ).order_by(*order_by_clauses(ordering))
    rows = (await db.execute(stmt)).all()

    defect_map = await load_defect_types(db, [image.id for image, *_ in rows])

    return [
        InspectionListItem(
            id=image.id,
            status=image.status,
            batch_number=batch.batch_number if batch is not None else None,
            board_number=board.board_number if board is not None else None,
            defect_types=defect_map.get(image.id, []),
            severity_max=analysis.severity_max if analysis is not None else None,
            review_status=analysis.review_status if analysis is not None else None,
            disposition_recommendation=(
                analysis.disposition_recommendation if analysis is not None else None
            ),
            disposition=board_disposition.decision if board_disposition is not None else None,
            failure_reason=image.failure_reason,
            created_at=image.created_at,
            processed_at=image.processed_at,
        )
        for image, board, batch, analysis, board_disposition in rows
    ]


async def get_inspection_detail(db: AsyncSession, inspection_id: uuid.UUID) -> InspectionDetail:
    """Full detail for the analysis detail screen (FE-03, section 11.5) and for individual
    report generation (FR-11, Issue 35) — both need the exact same shape.
    """
    row = (
        await db.execute(
            select(InspectionImage, Board, Batch)
            .select_from(InspectionImage)
            .outerjoin(Board, InspectionImage.board_id == Board.id)
            .outerjoin(Batch, Board.batch_id == Batch.id)
            .where(InspectionImage.id == inspection_id)
        )
    ).first()
    if row is None:
        raise ApiError("INSPECTION_NOT_FOUND", "Inspection image not found.", 404)
    image, board, batch = row

    analysis = await db.scalar(select(Analysis).where(Analysis.image_id == inspection_id))
    disposition = await db.scalar(
        select(BoardDisposition).where(BoardDisposition.image_id == inspection_id)
    )

    detection_rows = (
        await db.execute(
            select(Detection, ModelVersion.version)
            # Outer join: a manually-annotated detection (FR-10) has no `model_version_id`
            # at all, not just an unresolvable one — it must still appear on the detail
            # screen, just with `model_version=None`.
            .outerjoin(ModelVersion, Detection.model_version_id == ModelVersion.id)
            .where(Detection.image_id == inspection_id, Detection.is_reported.is_(True))
            .order_by(Detection.id)
        )
    ).all()

    duration_ms = None
    if image.processed_at is not None:
        duration_ms = int((image.processed_at - image.created_at).total_seconds() * 1000)

    analysis_out = None
    if analysis is not None:
        analysis_out = AnalysisOut.model_validate(analysis)
        # `Analysis` has no ORM relationship to its reviews (this codebase queries joins
        # explicitly rather than via SQLAlchemy relationships) — populated separately so
        # this matches `GET /api/v1/analyses/{id}` exactly, not just an always-empty default.
        reviews = await analyses_service.list_analysis_reviews(db, analysis.id)
        analysis_out.reviews = [AnalysisReviewOut.model_validate(review) for review in reviews]

    return InspectionDetail(
        id=image.id,
        status=image.status,
        board=InspectionBoard(
            board_number=board.board_number if board is not None else None,
            batch_number=batch.batch_number if batch is not None else None,
        ),
        failure_reason=image.failure_reason,
        created_at=image.created_at,
        processed_at=image.processed_at,
        duration_ms=duration_ms,
        detections=[
            DetectionOut(
                id=detection.id,
                defect_type=detection.defect_type,
                bbox=detection.bbox,
                confidence=detection.confidence,
                is_reported=detection.is_reported,
                model_version=version,
                review=detection.review,
                source=detection.source,
            )
            for detection, version in detection_rows
        ],
        analysis=analysis_out,
        disposition=(
            BoardDispositionOut.model_validate(disposition) if disposition is not None else None
        ),
    )


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
