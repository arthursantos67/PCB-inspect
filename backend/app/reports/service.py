import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Report
from app.models.enums import ReportType
from app.reports.schemas import ReportRequest

MAX_PAGE_SIZE = 100


def _serialize_filters(payload: ReportRequest) -> dict[str, Any] | None:
    if payload.type is ReportType.INDIVIDUAL:
        return {"inspection_id": str(payload.inspection_id)}
    if payload.type is ReportType.CONSOLIDATED:
        return payload.filters.model_dump(mode="json", exclude_none=True) if payload.filters else {}
    # executive
    return {
        "date_from": payload.date_from.isoformat() if payload.date_from else None,
        "date_to": payload.date_to.isoformat() if payload.date_to else None,
    }


async def create_report(db: AsyncSession, *, actor_id: uuid.UUID, payload: ReportRequest) -> Report:
    """Stages a `PENDING` `Report` row — the caller enqueues the generation task after this
    commits (mirrors `app.settings.models_service`'s register-then-evaluate pattern).
    """
    report = Report(
        type=payload.type,
        format=payload.format,
        filters=_serialize_filters(payload),
        requested_by=actor_id,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return report


async def get_report(db: AsyncSession, report_id: uuid.UUID) -> Report | None:
    return await db.get(Report, report_id)


async def list_reports(db: AsyncSession, *, page: int, page_size: int) -> tuple[int, list[Report]]:
    count = (await db.execute(select(func.count(Report.id)))).scalar() or 0
    rows = (
        (
            await db.execute(
                select(Report)
                .order_by(Report.created_at.desc(), Report.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return count, list(rows)
