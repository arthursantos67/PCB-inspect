import uuid
from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, model_validator

from app.models.enums import (
    AnalysisReviewStatus,
    BoardDispositionDecision,
    DefectType,
    ImageStatus,
    ReportFormat,
    ReportStatus,
    ReportType,
    Severity,
)

# Which output formats each report type supports (FR-11): individual and executive are
# always PDF; consolidated additionally supports the tabular formats a spreadsheet needs.
_ALLOWED_FORMATS: dict[ReportType, tuple[ReportFormat, ...]] = {
    ReportType.INDIVIDUAL: (ReportFormat.PDF,),
    ReportType.CONSOLIDATED: (ReportFormat.CSV, ReportFormat.XLSX, ReportFormat.PDF),
    ReportType.EXECUTIVE: (ReportFormat.PDF,),
}


class ReportFiltersIn(BaseModel):
    """Same filter shape as `GET /api/v1/inspections` (FR-07, Issue 8) — a consolidated
    report's params, so its contents can be generated with the exact same filter/order logic
    (`app.inspections.filters`) as the equivalent search query.
    """

    defect_type: list[DefectType] | None = None
    batch_number: str | None = None
    board_number: str | None = None
    status: ImageStatus | None = None
    severity: Severity | None = None
    review_status: AnalysisReviewStatus | None = None
    disposition: BoardDispositionDecision | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


class ReportRequest(BaseModel):
    """`POST /api/v1/reports` body (FR-11, UC-9). Which of `inspection_id`/`filters`/
    `date_from`+`date_to` applies depends on `type` — validated below rather than with three
    separate endpoints, since the three report types share everything else (async generation,
    status tracking, download).
    """

    type: ReportType
    format: ReportFormat
    # `individual` only.
    inspection_id: uuid.UUID | None = None
    # `consolidated` only — omitted/empty means "no filter" (every inspection), same as the
    # search screen with no filters applied.
    filters: ReportFiltersIn | None = None
    # `executive` only — omitted means "all time".
    date_from: datetime | None = None
    date_to: datetime | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> Self:
        allowed = _ALLOWED_FORMATS[self.type]
        if self.format not in allowed:
            raise ValueError(
                f"{self.type} reports only support: {', '.join(f.value for f in allowed)}"
            )
        if self.type is ReportType.INDIVIDUAL and self.inspection_id is None:
            raise ValueError("individual reports require inspection_id")
        return self


class ReportOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    type: ReportType
    format: ReportFormat
    filters: dict[str, Any] | None
    status: ReportStatus
    file_path: str | None
    row_count: int | None
    error_message: str | None
    requested_by: uuid.UUID
    created_at: datetime


class PaginatedReports(BaseModel):
    """Pagination envelope per PRD section 11.1, same shape as `PaginatedInspections`."""

    count: int
    next: str | None
    previous: str | None
    results: list[ReportOut]
