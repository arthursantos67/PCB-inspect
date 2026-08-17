"""`GET /api/v1/stats/{summary,trends,by-defect-type}` (FR-08, PRD section 11.2) — dashboard
aggregates (FE-02), cached in Redis with a 60s TTL (section 3.6). Cache invalidation on new
data is handled out-of-band by `app.tasks.pipeline` (best-effort) rather than here; a request
landing between an invalidation and the next write simply recomputes, same as any other miss.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models import User
from app.stats import service
from app.stats.cache import get_cached, set_cached
from app.stats.schemas import (
    Granularity,
    Period,
    RecentBatches,
    StatsByDefectType,
    StatsSummary,
    StatsTrends,
)

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])


def _cache_key(name: str, *parts: str) -> str:
    return ":".join(["stats", name, *parts])


@router.get("/summary", response_model=StatsSummary)
async def get_summary(
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> StatsSummary:
    window_from = date_from.isoformat() if date_from else "all"
    window_to = date_to.isoformat() if date_to else "all"
    cache_key = _cache_key("summary", f"{window_from}:{window_to}")

    cached = await get_cached(cache_key)
    if cached is not None:
        return StatsSummary.model_validate(cached)

    result = await service.compute_summary(db, date_from=date_from, date_to=date_to)
    await set_cached(cache_key, result.model_dump(mode="json"))
    return result


@router.get("/trends", response_model=StatsTrends)
async def get_trends(
    period: Period = Query(default="30d"),
    granularity: Granularity = Query(default="day"),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> StatsTrends:
    cache_key = _cache_key("trends", period, granularity)

    cached = await get_cached(cache_key)
    if cached is not None:
        return StatsTrends.model_validate(cached)

    result = await service.compute_trends(db, period=period, granularity=granularity)
    await set_cached(cache_key, result.model_dump(mode="json"))
    return result


@router.get("/by-defect-type", response_model=StatsByDefectType)
async def get_by_defect_type(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> StatsByDefectType:
    cache_key = _cache_key("by_defect_type", "all")

    cached = await get_cached(cache_key)
    if cached is not None:
        return StatsByDefectType.model_validate(cached)

    result = await service.compute_by_defect_type(db)
    await set_cached(cache_key, result.model_dump(mode="json"))
    return result


@router.get("/recent-batches", response_model=RecentBatches)
async def get_recent_batches(
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> RecentBatches:
    """Backs the dashboard's "Recently analyzed batches" card."""
    cache_key = _cache_key("recent_batches", str(limit))

    cached = await get_cached(cache_key)
    if cached is not None:
        return RecentBatches.model_validate(cached)

    result = RecentBatches(results=await service.compute_recent_batches(db, limit=limit))
    await set_cached(cache_key, result.model_dump(mode="json"))
    return result
