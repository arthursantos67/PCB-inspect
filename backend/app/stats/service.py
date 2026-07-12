"""Aggregation queries backing `GET /api/v1/stats/*` (FR-08). Every function here is a pure
read against the database — caching (TTL 60s, PRD section 3.6) is the router's concern, not
this module's, so these are also what a cache-miss recomputation calls directly.

RN-07: only `is_reported=true` detections feed any of these aggregates.
"""

from calendar import monthrange
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Detection, InspectionImage
from app.models.enums import DefectType, ImageStatus
from app.stats.schemas import (
    DefectTypeCount,
    Granularity,
    Period,
    StatsByDefectType,
    StatsSummary,
    StatsTrends,
    TrendPoint,
)

_PERIOD_DAYS: dict[Period, int] = {"7d": 7, "30d": 30, "90d": 90}


def period_start(period: Period, *, now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now - timedelta(days=_PERIOD_DAYS[period])


async def compute_summary(
    db: AsyncSession, *, date_from: datetime | None, date_to: datetime | None
) -> StatsSummary:
    conditions = [InspectionImage.status == ImageStatus.COMPLETED]
    if date_from is not None:
        conditions.append(InspectionImage.created_at >= date_from)
    if date_to is not None:
        conditions.append(InspectionImage.created_at <= date_to)

    total_inspected = (
        await db.execute(select(func.count(InspectionImage.id)).where(*conditions))
    ).scalar() or 0

    has_reported_defect = exists(
        select(1).where(
            Detection.image_id == InspectionImage.id, Detection.is_reported.is_(True)
        )
    )
    total_with_defects = (
        await db.execute(
            select(func.count(InspectionImage.id)).where(*conditions, has_reported_defect)
        )
    ).scalar() or 0

    last_24h_count = (
        await db.execute(
            select(func.count(InspectionImage.id)).where(
                InspectionImage.status == ImageStatus.COMPLETED,
                InspectionImage.processed_at >= datetime.now(UTC) - timedelta(hours=24),
            )
        )
    ).scalar() or 0

    quality_rate = (
        round((total_inspected - total_with_defects) / total_inspected * 100, 2)
        if total_inspected
        else 0.0
    )

    return StatsSummary(
        total_inspected=total_inspected,
        total_with_defects=total_with_defects,
        quality_rate=quality_rate,
        last_24h_count=last_24h_count,
    )


async def compute_by_defect_type(db: AsyncSession) -> StatsByDefectType:
    stmt = (
        select(Detection.defect_type, func.count(Detection.id))
        .select_from(Detection)
        .join(InspectionImage, Detection.image_id == InspectionImage.id)
        .where(Detection.is_reported.is_(True), InspectionImage.status == ImageStatus.COMPLETED)
        .group_by(Detection.defect_type)
    )
    counts = {defect_type: count for defect_type, count in (await db.execute(stmt)).all()}

    return StatsByDefectType(
        total=sum(counts.values()),
        # Every one of the 6 classes is always present (at `count=0` if unseen) so the
        # distribution bar chart (FE-02) has a stable, complete set of categories.
        counts=[DefectTypeCount(defect_type=dt, count=counts.get(dt, 0)) for dt in DefectType],
    )


async def compute_trends(
    db: AsyncSession, *, period: Period, granularity: Granularity
) -> StatsTrends:
    now = datetime.now(UTC)
    date_from = period_start(period, now=now)

    bucket_expr = func.date_trunc(granularity, InspectionImage.processed_at)
    stmt = (
        select(bucket_expr.label("bucket"), Detection.defect_type, func.count(Detection.id))
        .select_from(Detection)
        .join(InspectionImage, Detection.image_id == InspectionImage.id)
        .where(
            Detection.is_reported.is_(True),
            InspectionImage.status == ImageStatus.COMPLETED,
            InspectionImage.processed_at >= date_from,
        )
        .group_by(bucket_expr, Detection.defect_type)
    )
    rows = (await db.execute(stmt)).all()

    by_bucket: dict[date, dict[DefectType, int]] = defaultdict(dict)
    for bucket, defect_type, count in rows:
        by_bucket[bucket.date()][defect_type] = count

    points = [
        TrendPoint(
            bucket=bucket,
            total=sum(by_bucket.get(bucket, {}).values()),
            by_defect_type=by_bucket.get(bucket, {}),
        )
        for bucket in _generate_buckets(date_from.date(), now.date(), granularity)
    ]

    return StatsTrends(period=period, granularity=granularity, points=points)


def _generate_buckets(start: date, end: date, granularity: Granularity) -> list[date]:
    """The full set of bucket start-dates a chart should render across `[start, end]`, so
    days/weeks/months with zero reported defects still appear (as `total=0`) instead of being
    silently skipped — matching Postgres `date_trunc`'s bucket boundaries exactly (ISO weeks,
    calendar months) so these line up with the query results merged in by the caller.
    """
    if granularity == "day":
        span = (end - start).days
        return [start + timedelta(days=offset) for offset in range(span + 1)]

    if granularity == "week":
        current = start - timedelta(days=start.weekday())
        last = end - timedelta(days=end.weekday())
        buckets = []
        while current <= last:
            buckets.append(current)
            current += timedelta(days=7)
        return buckets

    current = start.replace(day=1)
    last = end.replace(day=1)
    buckets = []
    while current <= last:
        buckets.append(current)
        days_in_month = monthrange(current.year, current.month)[1]
        current = current.replace(day=days_in_month) + timedelta(days=1)
    return buckets
