import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.errors import ApiError
from app.db.session import get_db
from app.models import User
from app.models.enums import ReportStatus
from app.reports import service
from app.reports.schemas import PaginatedReports, ReportOut, ReportRequest
from app.tasks.reports import generate_report

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

MAX_PAGE_SIZE = service.MAX_PAGE_SIZE


def _page_url(request: Request, page: int, page_size: int) -> str:
    return str(request.url.include_query_params(page=page, page_size=page_size))


@router.post("", response_model=ReportOut, status_code=status.HTTP_202_ACCEPTED)
async def request_report(
    payload: ReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReportOut:
    """Generation runs on Celery (FR-11's "Async, Non-Blocking" acceptance criterion) — this
    returns immediately with a `PENDING` report the operator can poll/subscribe to (FE-07).
    """
    report = await service.create_report(db, actor_id=current_user.id, payload=payload)
    # Offloaded to a thread so the blocking Redis call never stalls the event loop (mirrors
    # app.settings.models_router's register-then-evaluate enqueue pattern).
    await asyncio.to_thread(generate_report.delay, str(report.id))
    return ReportOut.model_validate(report)


@router.get("", response_model=PaginatedReports)
async def list_reports(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> PaginatedReports:
    """Every generated report, most recent first (FE-07's "browse previously generated
    reports") — subject to the retention window (FR-13/FR-17): a purged report simply stops
    appearing here, same as any other retention-governed record.
    """
    count, reports = await service.list_reports(db, page=page, page_size=page_size)
    results = [ReportOut.model_validate(report) for report in reports]
    return PaginatedReports(
        count=count,
        next=_page_url(request, page + 1, page_size) if page * page_size < count else None,
        previous=_page_url(request, page - 1, page_size) if page > 1 else None,
        results=results,
    )


@router.get("/{report_id}/download")
async def download_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Streams the generated file directly from local disk (section 3.1), same pattern as
    `GET /api/v1/inspections/{id}/image`.
    """
    report = await service.get_report(db, report_id)
    if report is None:
        raise ApiError("RESOURCE_NOT_FOUND", "Report not found.", 404)

    if report.status != ReportStatus.COMPLETED or report.file_path is None:
        raise ApiError("REPORT_NOT_READY", "This report has not finished generating yet.", 409)

    path = Path(report.file_path)
    if not path.is_file():
        raise ApiError("RESOURCE_NOT_FOUND", "Report file not found on disk.", 404)

    return FileResponse(path, filename=path.name)
