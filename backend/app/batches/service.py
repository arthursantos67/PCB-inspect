"""Batch-level aggregation.

The inspections screen lists *batches* first and only drills into individual boards once one
is opened, so the counts, aggregated severity and aggregated status a batch row shows are
computed here rather than by loading every board into the client. The dashboard's
"Recently analyzed batches" card and the chat agent's batch tools read the same functions,
so a batch reads identically everywhere it appears.

RN-07 applies as everywhere else: only `is_reported=true` detections on `COMPLETED` images
count toward `defect_count`/`severity`.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.defects import severity_from_defect_counts
from app.models import Batch, Board, Detection, InspectionImage
from app.models.enums import DefectType, ImageStatus, Severity

# Worst-status-wins ordering for a batch's aggregate `status`: a batch with any FAILED image
# is flagged FAILED regardless of how far the rest got, and
# otherwise shows the *earliest* pipeline stage still in flight — only once every image has
# reached COMPLETED does the batch itself read as COMPLETED.
STATUS_PRIORITY: list[ImageStatus] = [
    ImageStatus.FAILED,
    ImageStatus.QUEUED,
    ImageStatus.PROCESSING,
    ImageStatus.DETECTED,
    ImageStatus.ANALYZING,
    ImageStatus.COMPLETED,
]
_STATUS_PRIORITY_CASE = case(
    *[(InspectionImage.status == status, index) for index, status in enumerate(STATUS_PRIORITY)],
    else_=len(STATUS_PRIORITY),
)

BatchOrdering = str


@dataclass(frozen=True)
class BatchAggregate:
    batch_id: uuid.UUID
    batch_number: str
    board_count: int
    completed_count: int
    boards_with_defects: int
    defect_count: int
    defect_counts: dict[DefectType, int]
    severity: Severity | None
    status: ImageStatus
    created_at: datetime
    last_activity_at: datetime

    @property
    def defect_rate(self) -> float:
        """Share of *completed* boards carrying at least one reported defect, 0..1."""
        if self.completed_count <= 0:
            return 0.0
        return round(self.boards_with_defects / self.completed_count, 4)


def _overview_query() -> Select[tuple[uuid.UUID, str, int, datetime, datetime, int, int]]:
    return (
        select(
            Batch.id,
            Batch.batch_number,
            func.min(_STATUS_PRIORITY_CASE),
            func.min(InspectionImage.created_at),
            func.max(InspectionImage.created_at),
            func.count(InspectionImage.id),
            func.count(case((InspectionImage.status == ImageStatus.COMPLETED, 1))),
        )
        .select_from(Batch)
        .join(Board, Board.batch_id == Batch.id)
        .join(InspectionImage, InspectionImage.board_id == Board.id)
        .group_by(Batch.id, Batch.batch_number)
    )


def _apply_filters(
    stmt: Select[Any],
    *,
    batch_number: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> Select[Any]:
    if batch_number:
        stmt = stmt.where(Batch.batch_number.ilike(f"%{batch_number}%"))
    if date_from is not None:
        stmt = stmt.where(InspectionImage.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(InspectionImage.created_at <= date_to)
    return stmt


async def _defect_counts_by_batch(
    db: AsyncSession, batch_ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, dict[DefectType, int]], dict[uuid.UUID, int]]:
    if not batch_ids:
        return {}, {}

    counts_stmt = (
        select(Batch.id, Detection.defect_type, func.count(Detection.id))
        .select_from(Detection)
        .join(InspectionImage, Detection.image_id == InspectionImage.id)
        .join(Board, InspectionImage.board_id == Board.id)
        .join(Batch, Board.batch_id == Batch.id)
        .where(
            Detection.is_reported.is_(True),
            InspectionImage.status == ImageStatus.COMPLETED,
            Batch.id.in_(batch_ids),
        )
        .group_by(Batch.id, Detection.defect_type)
    )
    defect_counts: dict[uuid.UUID, dict[DefectType, int]] = defaultdict(dict)
    for batch_id, defect_type, count in (await db.execute(counts_stmt)).all():
        defect_counts[batch_id][defect_type] = count

    boards_stmt = (
        select(Batch.id, func.count(func.distinct(InspectionImage.id)))
        .select_from(Detection)
        .join(InspectionImage, Detection.image_id == InspectionImage.id)
        .join(Board, InspectionImage.board_id == Board.id)
        .join(Batch, Board.batch_id == Batch.id)
        .where(
            Detection.is_reported.is_(True),
            InspectionImage.status == ImageStatus.COMPLETED,
            Batch.id.in_(batch_ids),
        )
        .group_by(Batch.id)
    )
    boards_with_defects = {
        batch_id: count for batch_id, count in (await db.execute(boards_stmt)).all()
    }
    return defect_counts, boards_with_defects


async def _aggregate_rows(db: AsyncSession, rows: list[Any]) -> list[BatchAggregate]:
    batch_ids = [row[0] for row in rows]
    defect_counts, boards_with_defects = await _defect_counts_by_batch(db, batch_ids)

    aggregates = []
    for (
        batch_id,
        batch_number,
        worst_priority,
        first_activity,
        last_activity,
        board_count,
        completed_count,
    ) in rows:
        counts = defect_counts.get(batch_id, {})
        batch_boards_with_defects = boards_with_defects.get(batch_id, 0)
        aggregates.append(
            BatchAggregate(
                batch_id=batch_id,
                batch_number=batch_number,
                board_count=board_count,
                completed_count=completed_count,
                boards_with_defects=batch_boards_with_defects,
                defect_count=sum(counts.values()),
                defect_counts=dict(counts),
                severity=severity_from_defect_counts(
                    counts,
                    defect_rate=(
                        batch_boards_with_defects / completed_count if completed_count else 0.0
                    ),
                ),
                status=STATUS_PRIORITY[worst_priority],
                created_at=first_activity,
                last_activity_at=last_activity,
            )
        )
    return aggregates


async def list_batches(
    db: AsyncSession,
    *,
    batch_number: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[int, list[BatchAggregate]]:
    """Most-recently-active batches first, with their aggregates. Returns
    `(total_matching, page)` so the caller can paginate.
    """
    count_stmt = select(func.count()).select_from(
        _apply_filters(
            _overview_query(), batch_number=batch_number, date_from=date_from, date_to=date_to
        ).subquery()
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        _apply_filters(
            _overview_query(), batch_number=batch_number, date_from=date_from, date_to=date_to
        )
        # Batches ingested in the same scan share a timestamp to the microsecond, so the
        # batch number breaks the tie: without it the order of tied rows is whatever the plan
        # happens to produce, which lets a page reshuffle between two refreshes and lets a
        # batch appear on two pages (or on neither) while paginating.
        .order_by(func.max(InspectionImage.created_at).desc(), Batch.batch_number.asc())
        .offset(offset)
        .limit(limit)
    )
    rows = [tuple(row) for row in (await db.execute(stmt)).all()]
    return total, await _aggregate_rows(db, rows)


async def get_batch(db: AsyncSession, batch_number: str) -> BatchAggregate | None:
    stmt = _overview_query().where(Batch.batch_number == batch_number)
    rows = [tuple(row) for row in (await db.execute(stmt)).all()]
    aggregates = await _aggregate_rows(db, rows)
    return aggregates[0] if aggregates else None


async def recent_batches(db: AsyncSession, *, limit: int = 10) -> list[BatchAggregate]:
    _total, aggregates = await list_batches(db, limit=limit)
    return aggregates
