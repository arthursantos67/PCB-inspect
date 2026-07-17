"""Query-parameter -> SQLAlchemy filter/order translation for `GET /api/v1/inspections`
(FR-07, PRD section 11.3). `review_status` and `disposition` (FR-10, Issue 33) filter on
`Analysis.review_status` and `BoardDisposition.decision` respectively — both already joined
onto the base query by `base_query` below.

Also reused by consolidated report generation (FR-11, Issue 35) so a report's contents are
guaranteed to match `GET /api/v1/inspections`'s filtering row-for-row rather than risk drifting
from a re-implementation.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import ColumnElement, Select, case, exists, select

from app.models import Analysis, Batch, Board, BoardDisposition, Detection, InspectionImage
from app.models.enums import (
    AnalysisReviewStatus,
    BoardDispositionDecision,
    DefectType,
    ImageStatus,
    Severity,
)

Ordering = Literal["created_at", "-created_at", "severity", "-severity"]


def base_query(*entities: Any) -> Select[Any]:
    """`InspectionImage` left-joined with everything `apply_filters` needs to filter on."""
    return (
        select(*entities)
        .select_from(InspectionImage)
        .outerjoin(Board, InspectionImage.board_id == Board.id)
        .outerjoin(Batch, Board.batch_id == Batch.id)
        .outerjoin(Analysis, Analysis.image_id == InspectionImage.id)
        .outerjoin(BoardDisposition, BoardDisposition.image_id == InspectionImage.id)
    )

_SEVERITY_RANK: ColumnElement[Any] = case(
    (Analysis.severity_max == Severity.CRITICAL, 3),
    (Analysis.severity_max == Severity.HIGH, 2),
    (Analysis.severity_max == Severity.MEDIUM, 1),
    (Analysis.severity_max == Severity.LOW, 0),
    else_=-1,
)


@dataclass
class InspectionFilters:
    defect_type: list[DefectType] | None = None
    batch_number: str | None = None
    board_number: str | None = None
    status: ImageStatus | None = None
    severity: Severity | None = None
    review_status: AnalysisReviewStatus | None = None
    disposition: BoardDispositionDecision | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


def apply_filters(stmt: Select[Any], filters: InspectionFilters) -> Select[Any]:
    """Assumes `stmt` already joins `Board`/`Batch`/`Analysis` onto `InspectionImage`
    (`base_query` above) — this only adds `WHERE` predicates.
    """
    if filters.defect_type:
        stmt = stmt.where(
            exists(
                select(1)
                .where(Detection.image_id == InspectionImage.id)
                .where(Detection.is_reported.is_(True))
                .where(Detection.defect_type.in_(filters.defect_type))
            )
        )
    if filters.batch_number:
        stmt = stmt.where(Batch.batch_number == filters.batch_number)
    if filters.board_number:
        stmt = stmt.where(Board.board_number == filters.board_number)
    if filters.status:
        stmt = stmt.where(InspectionImage.status == filters.status)
    if filters.severity:
        stmt = stmt.where(Analysis.severity_max == filters.severity)
    if filters.review_status:
        stmt = stmt.where(Analysis.review_status == filters.review_status)
    if filters.disposition:
        stmt = stmt.where(BoardDisposition.decision == filters.disposition)
    if filters.date_from:
        stmt = stmt.where(InspectionImage.created_at >= filters.date_from)
    if filters.date_to:
        stmt = stmt.where(InspectionImage.created_at <= filters.date_to)
    return stmt


def order_by_clauses(ordering: Ordering) -> list[ColumnElement[Any]]:
    """`InspectionImage.id` is always appended as a tiebreaker so pagination stays stable
    across pages even when many rows share the same primary sort value.
    """
    descending = ordering.startswith("-")
    key = ordering[1:] if descending else ordering
    column = _SEVERITY_RANK if key == "severity" else InspectionImage.created_at
    primary: ColumnElement[Any] = column.desc() if descending else column.asc()
    return [primary, InspectionImage.id.asc()]
