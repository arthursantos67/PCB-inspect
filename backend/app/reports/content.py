"""Assembles the data each report type needs, then hands it to the matching format generator
(`app.reports.generators`). Consolidated reports reuse `app.inspections.filters`/`.service`
(Issue 8) so their contents can never drift from `GET /api/v1/inspections` for the same
filters; executive summaries reuse `app.stats.service` (Issue 9) directly rather than the
cached router functions (same rationale as that module's own docstring).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.inspections import service as inspections_service
from app.inspections.filters import InspectionFilters
from app.models import Report
from app.models.enums import ReportFormat, ReportType
from app.reports.generators import csv as csv_generator
from app.reports.generators import pdf as pdf_generator
from app.reports.generators import xlsx as xlsx_generator
from app.reports.schemas import ReportFiltersIn
from app.stats import service as stats_service


@dataclass
class GenerationResult:
    file_path: Path
    row_count: int | None


def _output_path(output_dir: Path, report: Report) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{report.type.value}-{report.id}.{report.format.value}"


async def _generate_individual(
    db: AsyncSession, report: Report, output_dir: Path
) -> GenerationResult:
    filters = report.filters or {}
    raw_inspection_id = filters.get("inspection_id")
    if not raw_inspection_id:
        raise ApiError("REPORT_INVALID_PARAMS", "individual report is missing inspection_id.", 422)

    detail = await inspections_service.get_inspection_detail(db, uuid.UUID(raw_inspection_id))
    path = _output_path(output_dir, report)
    pdf_generator.write_individual(detail, path)
    return GenerationResult(file_path=path, row_count=len(detail.detections))


async def _generate_consolidated(
    db: AsyncSession, report: Report, output_dir: Path
) -> GenerationResult:
    filters_in = ReportFiltersIn.model_validate(report.filters or {})
    filters = InspectionFilters(**filters_in.model_dump())
    rows = await inspections_service.list_all_inspections(db, filters)

    path = _output_path(output_dir, report)
    if report.format is ReportFormat.CSV:
        csv_generator.write_consolidated(rows, path)
    elif report.format is ReportFormat.XLSX:
        xlsx_generator.write_consolidated(rows, path)
    else:
        pdf_generator.write_consolidated(rows, path)
    return GenerationResult(file_path=path, row_count=len(rows))


async def _generate_executive(
    db: AsyncSession, report: Report, output_dir: Path
) -> GenerationResult:
    filters = report.filters or {}
    raw_date_from = filters.get("date_from")
    raw_date_to = filters.get("date_to")
    date_from = datetime.fromisoformat(raw_date_from) if raw_date_from else None
    date_to = datetime.fromisoformat(raw_date_to) if raw_date_to else None

    summary = await stats_service.compute_summary(db, date_from=date_from, date_to=date_to)
    by_defect_type = await stats_service.compute_by_defect_type(
        db, date_from=date_from, date_to=date_to
    )
    top_batches = await stats_service.compute_top_batches(
        db, date_from=date_from, date_to=date_to
    )

    path = _output_path(output_dir, report)
    pdf_generator.write_executive(
        summary=summary,
        by_defect_type=by_defect_type,
        top_batches=top_batches,
        date_from=date_from,
        date_to=date_to,
        path=path,
    )
    return GenerationResult(file_path=path, row_count=None)


async def generate(db: AsyncSession, report: Report, output_dir: Path) -> GenerationResult:
    if report.type is ReportType.INDIVIDUAL:
        return await _generate_individual(db, report, output_dir)
    if report.type is ReportType.CONSOLIDATED:
        return await _generate_consolidated(db, report, output_dir)
    return await _generate_executive(db, report, output_dir)
