import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.models.enums import DatasetExportStatus, DefectType, DetectionReview


class DatasetExportFiltersIn(BaseModel):
    """`POST /api/v1/dataset-exports` filters (FR-18): period, defect types, and review
    status. Only `confirmed`/`false_positive` are accepted for `review_status` (mirrors
    `DetectionFeedbackRequest`) — `unreviewed` detections carry no export-worthy signal yet, so
    they're never eligible regardless of this filter.
    """

    defect_type: list[DefectType] | None = None
    review_status: (
        list[Literal[DetectionReview.CONFIRMED, DetectionReview.FALSE_POSITIVE]] | None
    ) = None
    date_from: datetime | None = None
    date_to: datetime | None = None


class DatasetExportRequest(BaseModel):
    """Omitted/empty filters means every reviewed detection: every confirmed label, every
    false-positive correction, and every manual annotation (already pre-confirmed, FR-10).
    """

    filters: DatasetExportFiltersIn | None = None


class DatasetExportOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    filters: dict[str, Any] | None
    status: DatasetExportStatus
    manifest: dict[str, Any] | None
    file_path: str | None
    error_message: str | None
    requested_by: uuid.UUID
    created_at: datetime


class PaginatedDatasetExports(BaseModel):
    """Pagination envelope per PRD section 11.1, same shape as `PaginatedReports`."""

    count: int
    next: str | None
    previous: str | None
    results: list[DatasetExportOut]
