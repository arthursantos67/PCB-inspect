import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.datasets.schemas import DatasetExportRequest
from app.models import DatasetExport

MAX_PAGE_SIZE = 100


def _serialize_filters(payload: DatasetExportRequest) -> dict[str, Any]:
    return payload.filters.model_dump(mode="json", exclude_none=True) if payload.filters else {}


async def create_dataset_export(
    db: AsyncSession, *, actor_id: uuid.UUID, payload: DatasetExportRequest
) -> DatasetExport:
    """Stages a `PENDING` `DatasetExport` row — the caller enqueues the generation task after
    this commits (mirrors `app.reports.service.create_report`).
    """
    export = DatasetExport(filters=_serialize_filters(payload), requested_by=actor_id)
    db.add(export)
    await db.commit()
    await db.refresh(export)
    return export


async def get_dataset_export(db: AsyncSession, export_id: uuid.UUID) -> DatasetExport | None:
    return await db.get(DatasetExport, export_id)


async def list_dataset_exports(
    db: AsyncSession, *, page: int, page_size: int
) -> tuple[int, list[DatasetExport]]:
    count = (await db.execute(select(func.count(DatasetExport.id)))).scalar() or 0
    rows = (
        (
            await db.execute(
                select(DatasetExport)
                .order_by(DatasetExport.created_at.desc(), DatasetExport.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return count, list(rows)
