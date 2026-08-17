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
from app.reports.strings import ReportLanguage

# Which output formats each report type supports (FR-11). Individual reports now accept the
# tabular formats too: the CSV is one row per defect occurrence, which is as meaningful for a
# single board as it is for a whole batch. The
# executive summary stays PDF only, since it has no per board rows to tabulate.
_ALLOWED_FORMATS: dict[ReportType, tuple[ReportFormat, ...]] = {
    ReportType.INDIVIDUAL: (ReportFormat.PDF, ReportFormat.CSV, ReportFormat.XLSX),
    ReportType.CONSOLIDATED: (ReportFormat.CSV, ReportFormat.XLSX, ReportFormat.PDF),
    ReportType.EXECUTIVE: (ReportFormat.PDF,),
}


class ReportFiltersIn(BaseModel):
    """Same filter shape as `GET /api/v1/inspections` (FR-07, Issue 8): a consolidated
    report's params, so its contents can be generated with the exact same filter/order logic
    (`app.inspections.filters`) as the equivalent search query.

    `board_numbers` is the one addition: the reports screen picks boards from a list of the
    chosen batch's boards rather than having the operator type
    one name, so the request has to be able to name several at once.
    """

    defect_type: list[DefectType] | None = None
    batch_number: str | None = None
    board_number: str | None = None
    board_numbers: list[str] | None = None
    status: ImageStatus | None = None
    severity: Severity | None = None
    review_status: AnalysisReviewStatus | None = None
    disposition: BoardDispositionDecision | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


class ReportRequest(BaseModel):
    """`POST /api/v1/reports` body (FR-11, UC-9). Which of `inspection_id`/`filters`/
    `date_from`+`date_to` applies depends on `type`, validated below rather than with three
    separate endpoints, since the three report types share everything else (async generation,
    status tracking, download).
    """

    type: ReportType
    format: ReportFormat
    # Language of the generated content. Applies to every heading, table header and
    # analytical passage the report itself writes, and since issue #50 to the stored per
    # board analysis text as well, which is translated into it.
    # Omitted means "the station's language" (`app.settings.service.get_language`), resolved
    # when the request is recorded so the stored filters always name a concrete language and a
    # report downloaded a month later still reads the way it did when it was generated.
    language: ReportLanguage | None = None
    # `individual` only.
    inspection_id: uuid.UUID | None = None
    # `consolidated` only. Omitted/empty means "no filter" (every inspection), same as the
    # search screen with no filters applied.
    filters: ReportFiltersIn | None = None
    # `executive` only. Omitted means "all time".
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


def language_of(filters: dict[str, Any] | None) -> ReportLanguage:
    """The language stored alongside a report's filters. Reports created before language
    tracking existed have no `language` key at all and read as English, which is what they
    were generated in.
    """
    raw = (filters or {}).get("language")
    try:
        return ReportLanguage(raw) if raw else ReportLanguage.EN
    except ValueError:
        return ReportLanguage.EN


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
