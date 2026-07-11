import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.enums import ImageStatus

FileOutcome = Literal["ingested", "duplicate", "failed", "skipped"]


class ScanRequest(BaseModel):
    path: str


class FileResult(BaseModel):
    path: str
    outcome: FileOutcome
    image_id: uuid.UUID | None = None
    reason: str | None = None


class ScanSummary(BaseModel):
    path: str
    discovered: int
    ingested: int
    duplicate: int
    failed: int
    skipped: int
    files: list[FileResult]


class ImportSummary(BaseModel):
    ingested: int
    duplicate: int
    failed: int
    files: list[FileResult]


WatchStatus = Literal["watching", "paused", "not_configured", "error"]


class IngestionStatus(BaseModel):
    status: WatchStatus
    watch_root_path: str | None
    watch_mode_enabled: bool
    files_discovered: int
    files_ingested: int
    files_failed: int
    detail: str | None = None


class InspectionProgress(BaseModel):
    """Current pipeline status for polling (FR-04), as a fallback to SSE (FR-14)."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    status: ImageStatus
    failure_reason: str | None
    created_at: datetime
    processed_at: datetime | None
