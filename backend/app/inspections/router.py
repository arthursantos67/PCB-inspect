import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.errors import ApiError
from app.db.session import get_db
from app.inspections import service
from app.inspections.filters import (
    InspectionFilters,
    Ordering,
    apply_filters,
    base_query,
    order_by_clauses,
)
from app.inspections.schemas import (
    AgentAnalysisRequested,
    AnnotationRequest,
    BoardDispositionOut,
    DetectionOut,
    DispositionRequest,
    InspectionDetail,
    InspectionListItem,
    PaginatedInspections,
)
from app.inspections.state import InvalidTransitionError, transition
from app.models import Analysis, Batch, Board, BoardDisposition, InspectionImage, User
from app.models.enums import (
    AnalysisReviewStatus,
    BoardDispositionDecision,
    DefectType,
    ImageStatus,
    Severity,
)
from app.tasks.pipeline import run_agent_analysis

router = APIRouter(prefix="/api/v1/inspections", tags=["inspections"])

MAX_PAGE_SIZE = 100


def _page_url(request: Request, page: int, page_size: int) -> str:
    return str(request.url.include_query_params(page=page, page_size=page_size))


@router.get("", response_model=PaginatedInspections)
async def list_inspections(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
    defect_type: list[DefectType] | None = Query(default=None),
    batch_number: str | None = Query(default=None),
    board_number: str | None = Query(default=None),
    status: ImageStatus | None = Query(default=None),
    severity: Severity | None = Query(default=None),
    review_status: AnalysisReviewStatus | None = Query(default=None),
    disposition: BoardDispositionDecision | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    ordering: Ordering = Query(default="-created_at"),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> PaginatedInspections:
    filters = InspectionFilters(
        defect_type=defect_type,
        batch_number=batch_number,
        board_number=board_number,
        status=status,
        severity=severity,
        review_status=review_status,
        disposition=disposition,
        date_from=date_from,
        date_to=date_to,
    )

    count_stmt = apply_filters(base_query(func.count(InspectionImage.id)), filters)
    count = (await db.execute(count_stmt)).scalar() or 0

    data_stmt = (
        apply_filters(
            base_query(InspectionImage, Board, Batch, Analysis, BoardDisposition), filters
        )
        .order_by(*order_by_clauses(ordering))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(data_stmt)).all()

    defect_map = await service.load_defect_types(db, [image.id for image, *_ in rows])

    results = [
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

    return PaginatedInspections(
        count=count,
        next=_page_url(request, page + 1, page_size) if page * page_size < count else None,
        previous=_page_url(request, page - 1, page_size) if page > 1 else None,
        results=results,
    )


@router.get("/{inspection_id}", response_model=InspectionDetail)
async def get_inspection(
    inspection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> InspectionDetail:
    """Full detail for the analysis detail screen (FE-03, section 11.5); also FR-04's
    progress-polling fallback to SSE — `detections`/`analysis` are just empty/`None` until
    the pipeline reaches that stage. Also reused by individual report generation (FR-11,
    Issue 35) via `app.inspections.service.get_inspection_detail`.
    """
    return await service.get_inspection_detail(db, inspection_id)


@router.get("/{inspection_id}/image")
async def get_inspection_image(
    inspection_id: uuid.UUID,
    variant: Literal["original", "annotated"] = Query(default="original"),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Streams the image directly from local disk (section 3.1) — gated only by the
    endpoint's own session auth, no expiring-URL mechanism needed.
    """
    image = await db.get(InspectionImage, inspection_id)
    if image is None:
        raise ApiError("INSPECTION_NOT_FOUND", "Inspection image not found.", 404)

    path_str = image.original_path if variant == "original" else image.annotated_path
    if path_str is None:
        raise ApiError(
            "INSPECTION_NOT_READY", "The annotated image has not been generated yet.", 409
        )

    path = Path(path_str)
    if not path.is_file():
        raise ApiError("RESOURCE_NOT_FOUND", "Image file not found on disk.", 404)

    return FileResponse(path)


@router.post(
    "/{inspection_id}/agent-analysis",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AgentAnalysisRequested,
)
async def request_agent_analysis(
    inspection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> AgentAnalysisRequested:
    """Explicit trigger for the Analyst/Reviewer/Summarizer chain (FE-03, `on_demand` mode,
    FR-06/issue #31) — usable any time a completed, baseline-only inspection exists,
    independent of the current `agent_analysis_mode`: the policy governs *automatic*
    triggering (Issue 31's Policy Honored criterion), this endpoint is always the explicit
    override FE-03 needs regardless of which mode is configured.
    """
    image = await db.get(InspectionImage, inspection_id)
    if image is None:
        raise ApiError("INSPECTION_NOT_FOUND", "Inspection image not found.", 404)

    analysis = await db.scalar(select(Analysis).where(Analysis.image_id == inspection_id))
    if analysis is None:
        raise ApiError(
            "INSPECTION_NOT_READY", "No baseline analysis available for this inspection yet.", 409
        )

    try:
        transition(image, ImageStatus.ANALYZING)
    except InvalidTransitionError as exc:
        raise ApiError(
            "INSPECTION_NOT_READY",
            "Inspection must be COMPLETED before requesting an in-depth agent analysis.",
            409,
        ) from exc

    await db.commit()
    # Offloaded to a thread so the blocking Redis call never stalls the event loop (mirrors
    # app.ingestion.service's enqueue-after-commit pattern, section 3.5).
    await asyncio.to_thread(run_agent_analysis.delay, str(image.id))
    return AgentAnalysisRequested()


@router.post("/{inspection_id}/disposition", response_model=BoardDispositionOut)
async def set_board_disposition(
    inspection_id: uuid.UUID,
    payload: DispositionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BoardDispositionOut:
    """Records a board's final disposition (FR-10, UC-5) — shows on this detail screen and
    on search results (`disposition` filter/field, Issue 8). Audited (FR-16).
    """
    disposition = await service.set_disposition(
        db, actor_id=current_user.id, image_id=inspection_id, decision=payload.decision
    )
    return BoardDispositionOut.model_validate(disposition)


@router.post(
    "/{inspection_id}/annotations",
    response_model=DetectionOut,
    status_code=status.HTTP_201_CREATED,
)
async def annotate_inspection(
    inspection_id: uuid.UUID,
    payload: AnnotationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DetectionOut:
    """Annotates a defect the model missed by drawing a bbox + class directly in the image
    viewer (FR-10, Issue 10) — creates a `Detection` row flagged `source=manual`. Audited
    (FR-16) and is the input dataset export (FR-18) later packages into training data.
    """
    detection = await service.annotate_detection(
        db,
        actor_id=current_user.id,
        image_id=inspection_id,
        defect_type=payload.defect_type,
        bbox=payload.bbox,
    )
    return DetectionOut(
        id=detection.id,
        defect_type=detection.defect_type,
        bbox=detection.bbox,
        confidence=detection.confidence,
        is_reported=detection.is_reported,
        model_version=None,
        review=detection.review,
        source=detection.source,
    )
