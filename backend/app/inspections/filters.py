"""Query-parameter -> SQLAlchemy filter/order translation for `GET /api/v1/inspections`
(FR-07, PRD section 11.3). Scoped to the filters Issue 8 specifies — defect type, batch,
board, status, severity, date range — `review_status`/`disposition` wait on the entities
that back them (`AnalysisReview`/`BoardDisposition`, FR-10, a later issue).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import ColumnElement, Select, case, exists, select

from app.models import Analysis, Batch, Board, Detection, InspectionImage
from app.models.enums import DefectType, ImageStatus, Severity

Ordering = Literal["created_at", "-created_at", "severity", "-severity"]

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
    date_from: datetime | None = None
    date_to: datetime | None = None


def apply_filters(stmt: Select[Any], filters: InspectionFilters) -> Select[Any]:
    """Assumes `stmt` already joins `Board`/`Batch`/`Analysis` onto `InspectionImage`
    (`app.inspections.router._base_query`) — this only adds `WHERE` predicates.
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
