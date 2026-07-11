import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.db.session import get_db
from app.ingestion import service
from app.ingestion.schemas import (
    ImportSummary,
    IngestionStatus,
    InspectionProgress,
    ScanRequest,
    ScanSummary,
)
from app.models import InspectionImage, User
from app.models.enums import ImageSource

router = APIRouter(prefix="/api/v1/inspections", tags=["ingestion"])


@router.post("/scan", response_model=ScanSummary, status_code=status.HTTP_202_ACCEPTED)
async def scan(
    payload: ScanRequest,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> ScanSummary:
    return await service.scan_directory(db, Path(payload.path), source=ImageSource.DIRECTORY_SCAN)


@router.post("/import", response_model=ImportSummary, status_code=status.HTTP_202_ACCEPTED)
async def import_files(
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> ImportSummary:
    max_size_mb = await service.get_import_max_size_mb(db)
    return await service.import_files(
        db,
        uploads=files,
        created_by=current_user.id,
        max_size_bytes=int(max_size_mb * 1024 * 1024),
        app_data_dir=settings.app_data_dir,
    )


@router.get("/ingestion-status", response_model=IngestionStatus)
async def ingestion_status(
    db: AsyncSession = Depends(get_db), _current_user: User = Depends(get_current_user)
) -> IngestionStatus:
    return await service.get_ingestion_status(db)


@router.get("/{inspection_id}", response_model=InspectionProgress)
async def get_progress(
    inspection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> InspectionImage:
    image = await db.get(InspectionImage, inspection_id)
    if image is None:
        raise ApiError("INSPECTION_NOT_FOUND", "Inspection image not found.", 404)
    return image
