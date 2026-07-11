import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.inspections.filters import InspectionFilters, Ordering, apply_filters, order_by_clauses
from app.inspections.schemas import InspectionListItem, PaginatedInspections
from app.models import Analysis, Batch, Board, Detection, InspectionImage, User
from app.models.enums import DefectType, ImageStatus, Severity

router = APIRouter(prefix="/api/v1/inspections", tags=["inspections"])

MAX_PAGE_SIZE = 100


def _base_query(*entities: Any) -> Select[Any]:
    return (
        select(*entities)
        .select_from(InspectionImage)
        .outerjoin(Board, InspectionImage.board_id == Board.id)
        .outerjoin(Batch, Board.batch_id == Batch.id)
        .outerjoin(Analysis, Analysis.image_id == InspectionImage.id)
    )


async def _load_defect_types(
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
        date_from=date_from,
        date_to=date_to,
    )

    count_stmt = apply_filters(_base_query(func.count(InspectionImage.id)), filters)
    count = (await db.execute(count_stmt)).scalar() or 0

    data_stmt = (
        apply_filters(_base_query(InspectionImage, Board, Batch, Analysis), filters)
        .order_by(*order_by_clauses(ordering))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(data_stmt)).all()

    defect_map = await _load_defect_types(db, [image.id for image, _, _, _ in rows])

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
            failure_reason=image.failure_reason,
            created_at=image.created_at,
            processed_at=image.processed_at,
        )
        for image, board, batch, analysis in rows
    ]

    return PaginatedInspections(
        count=count,
        next=_page_url(request, page + 1, page_size) if page * page_size < count else None,
        previous=_page_url(request, page - 1, page_size) if page > 1 else None,
        results=results,
    )
