from pathlib import Path

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.ingestion import service
from app.ingestion.schemas import IngestionStatus, ScanRequest, ScanSummary
from app.models import User
from app.models.enums import ImageSource

router = APIRouter(prefix="/api/v1/inspections", tags=["ingestion"])


@router.post("/scan", response_model=ScanSummary, status_code=status.HTTP_202_ACCEPTED)
async def scan(
    payload: ScanRequest,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> ScanSummary:
    """One-off scan of a directory laid out like the watch root (`<root>/<batch>/<board>.jpg`).

    Same code path watch mode polls on a timer, run once on demand — files are read in place
    from the operator's own filesystem and never uploaded or copied.
    """
    return await service.scan_directory(db, Path(payload.path), source=ImageSource.DIRECTORY_SCAN)


@router.get("/ingestion-status", response_model=IngestionStatus)
async def ingestion_status(
    db: AsyncSession = Depends(get_db), _current_user: User = Depends(get_current_user)
) -> IngestionStatus:
    return await service.get_ingestion_status(db)
