"""`GET /api/v1/batches` — the batch-first inspections list.

The per-board list (`GET /api/v1/inspections?batch_number=...`) is unchanged and is what the
UI drills into once a batch row is opened.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.batches import service
from app.batches.schemas import BatchListItem, PaginatedBatches
from app.core.errors import ApiError
from app.db.session import get_db
from app.models import User

router = APIRouter(prefix="/api/v1/batches", tags=["batches"])

MAX_PAGE_SIZE = 100


@router.get("", response_model=PaginatedBatches)
async def list_batches(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
    batch_number: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> PaginatedBatches:
    count, aggregates = await service.list_batches(
        db,
        batch_number=batch_number,
        date_from=date_from,
        date_to=date_to,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return PaginatedBatches(
        count=count, results=[BatchListItem.from_aggregate(item) for item in aggregates]
    )


@router.get("/{batch_number}", response_model=BatchListItem)
async def get_batch(
    batch_number: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> BatchListItem:
    aggregate = await service.get_batch(db, batch_number)
    if aggregate is None:
        raise ApiError("RESOURCE_NOT_FOUND", "Batch not found.", 404)
    return BatchListItem.from_aggregate(aggregate)
