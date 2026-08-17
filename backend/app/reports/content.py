"""Assembles the report a request asks for, then hands it to the matching format generator
(`app.reports.generators`).

Every type goes through the same three steps: resolve the request to a set of inspections,
load them and their batch aggregates
(`app.reports.dataset`), then have the analytical prose written over those figures
(`app.reports.narrative`). Which inspections is still resolved by `app.inspections.filters`
/`.service` (Issue 8), so a report's contents can never drift from `GET /api/v1/inspections`
for the same filters; the executive summary's period aggregates still come from
`app.stats.service` (Issue 9) rather than the cached router functions.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.inspections import service as inspections_service
from app.inspections.filters import InspectionFilters
from app.models import Report
from app.models.enums import ReportFormat, ReportType
from app.reports import dataset as dataset_module
from app.reports import narrative as narrative_module
from app.reports.document import ExecutiveFigures, ReportDocument
from app.reports.generators import csv as csv_generator
from app.reports.generators import pdf as pdf_generator
from app.reports.generators import xlsx as xlsx_generator
from app.reports.schemas import ReportFiltersIn, language_of
from app.reports.strings import ReportLanguage
from app.stats import service as stats_service


@dataclass
class GenerationResult:
    file_path: Path
    row_count: int | None


def _output_path(output_dir: Path, report: Report) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{report.type.value}-{report.id}.{report.format.value}"


def _parse_datetime(raw: object) -> datetime | None:
    return datetime.fromisoformat(str(raw)) if raw else None


async def _individual_dataset(
    db: AsyncSession, filters: dict[str, object], language: ReportLanguage
) -> dataset_module.ReportDataset:
    raw_inspection_id = filters.get("inspection_id")
    if not raw_inspection_id:
        raise ApiError("REPORT_INVALID_PARAMS", "individual report is missing inspection_id.", 422)

    inspection_id = uuid.UUID(str(raw_inspection_id))
    # Routed through the detail loader purely for its not-found handling, so a report for a
    # purged inspection fails with the same INSPECTION_NOT_FOUND the API returns instead of
    # silently producing an empty document.
    await inspections_service.get_inspection_detail(db, inspection_id)
    return await dataset_module.build_dataset(db, [inspection_id], language=language)


async def _filtered_dataset(
    db: AsyncSession, filters: InspectionFilters, language: ReportLanguage
) -> dataset_module.ReportDataset:
    rows = await inspections_service.list_all_inspections(db, filters)
    ordered_ids = [row.id for row in rows]
    return await dataset_module.build_dataset(
        db, ordered_ids, ordered_ids=ordered_ids, language=language
    )


async def _build_document(
    db: AsyncSession, report: Report
) -> ReportDocument:
    raw_filters = dict(report.filters or {})
    language = language_of(raw_filters)
    date_from = _parse_datetime(raw_filters.get("date_from"))
    date_to = _parse_datetime(raw_filters.get("date_to"))
    executive: ExecutiveFigures | None = None

    if report.type is ReportType.INDIVIDUAL:
        dataset = await _individual_dataset(db, raw_filters, language)
    elif report.type is ReportType.CONSOLIDATED:
        filters_in = ReportFiltersIn.model_validate(
            {key: value for key, value in raw_filters.items() if key != "language"}
        )
        dataset = await _filtered_dataset(
            db, InspectionFilters(**filters_in.model_dump()), language
        )
    else:
        dataset = await dataset_module.build_period_dataset(
            db, date_from=date_from, date_to=date_to
        )
        executive = ExecutiveFigures(
            summary=await stats_service.compute_summary(db, date_from=date_from, date_to=date_to),
            by_defect_type=await stats_service.compute_by_defect_type(
                db, date_from=date_from, date_to=date_to
            ),
            top_batches=await stats_service.compute_top_batches(
                db, date_from=date_from, date_to=date_to
            ),
        )

    narrative = await narrative_module.build_narrative(db, dataset, language=language)
    board = dataset.boards[0] if dataset.boards else None
    return ReportDocument(
        type=report.type,
        language=language,
        dataset=dataset,
        narrative=narrative,
        generated_at=datetime.now(UTC),
        date_from=date_from,
        date_to=date_to,
        board_number=board.board_number if board is not None else None,
        executive=executive,
    )


async def generate(db: AsyncSession, report: Report, output_dir: Path) -> GenerationResult:
    document = await _build_document(db, report)
    path = _output_path(output_dir, report)

    row_count: int | None
    if report.format is ReportFormat.CSV:
        row_count = csv_generator.write(document, path)
    elif report.format is ReportFormat.XLSX:
        row_count = xlsx_generator.write(document, path)
    else:
        pdf_generator.write(document, path)
        # The PDF's unit of content is the board section, not the spreadsheet row; the
        # executive summary has none at all, so it keeps reporting no row count.
        row_count = None if report.type is ReportType.EXECUTIVE else len(document.dataset.boards)

    return GenerationResult(file_path=path, row_count=row_count)


__all__ = ["GenerationResult", "ReportLanguage", "generate"]
