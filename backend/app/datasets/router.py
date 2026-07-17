import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.errors import ApiError
from app.datasets import service
from app.datasets.schemas import DatasetExportOut, DatasetExportRequest, PaginatedDatasetExports
from app.db.session import get_db
from app.models import User
from app.models.enums import DatasetExportStatus
from app.tasks.dataset_exports import generate_dataset_export

router = APIRouter(prefix="/api/v1/dataset-exports", tags=["dataset-exports"])

MAX_PAGE_SIZE = service.MAX_PAGE_SIZE


def _page_url(request: Request, page: int, page_size: int) -> str:
    return str(request.url.include_query_params(page=page, page_size=page_size))


@router.post("", response_model=DatasetExportOut, status_code=status.HTTP_202_ACCEPTED)
async def request_dataset_export(
    payload: DatasetExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DatasetExportOut:
    """Generation runs on Celery (FR-18) — returns immediately with a `PENDING` export the
    operator can poll/subscribe to, mirroring `app.reports.router.request_report`.
    """
    export = await service.create_dataset_export(db, actor_id=current_user.id, payload=payload)
    # Offloaded to a thread so the blocking Redis call never stalls the event loop (mirrors
    # app.reports.router's enqueue pattern).
    await asyncio.to_thread(generate_dataset_export.delay, str(export.id))
    return DatasetExportOut.model_validate(export)


@router.get("", response_model=PaginatedDatasetExports)
async def list_dataset_exports(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> PaginatedDatasetExports:
    """Every generated dataset export, most recent first — subject to the retention window
    (FR-13/FR-17): a purged export simply stops appearing here.
    """
    count, exports = await service.list_dataset_exports(db, page=page, page_size=page_size)
    results = [DatasetExportOut.model_validate(export) for export in exports]
    return PaginatedDatasetExports(
        count=count,
        next=_page_url(request, page + 1, page_size) if page * page_size < count else None,
        previous=_page_url(request, page - 1, page_size) if page > 1 else None,
        results=results,
    )


@router.get("/{export_id}/download")
async def download_dataset_export(
    export_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Streams the generated ZIP directly from local disk, same pattern as report downloads."""
    export = await service.get_dataset_export(db, export_id)
    if export is None:
        raise ApiError("RESOURCE_NOT_FOUND", "Dataset export not found.", 404)

    if export.status != DatasetExportStatus.COMPLETED or export.file_path is None:
        raise ApiError(
            "DATASET_EXPORT_NOT_READY",
            "This dataset export has not finished generating yet.",
            409,
        )

    path = Path(export.file_path)
    if not path.is_file():
        raise ApiError("RESOURCE_NOT_FOUND", "Dataset export file not found on disk.", 404)

    return FileResponse(path, filename=path.name)
