"""PDF writer (FR-11) — all three report types can render to PDF, so this one module covers
`individual`, `consolidated`, and `executive` rather than splitting by type (unlike
`app.reports.generators.{csv,xlsx}`, which only ever serve `consolidated`).
"""

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.inspections.schemas import InspectionDetail, InspectionListItem
from app.stats.schemas import StatsByDefectType, StatsSummary

_STYLES = getSampleStyleSheet()
_TITLE = ParagraphStyle("ReportTitle", parent=_STYLES["Title"])
_HEADING = ParagraphStyle("ReportHeading", parent=_STYLES["Heading2"])
_BODY = _STYLES["BodyText"]

_TABLE_STYLE = TableStyle(
    [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
    ]
)


def _doc(path: Path) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        str(path),
        pagesize=LETTER,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
    )


def _generated_at_line() -> Paragraph:
    return Paragraph(
        f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}", _STYLES["Normal"]
    )


def write_individual(detail: InspectionDetail, path: Path) -> None:
    story = [
        Paragraph("Individual Inspection Report", _TITLE),
        _generated_at_line(),
        Spacer(1, 0.5 * cm),
        Paragraph(
            f"Batch {detail.board.batch_number or '—'} / Board {detail.board.board_number or '—'}",
            _HEADING,
        ),
        Paragraph(f"Status: {detail.status.value}", _BODY),
        Paragraph(f"Created: {detail.created_at.isoformat()}", _BODY),
        Spacer(1, 0.5 * cm),
        Paragraph("Detections", _HEADING),
    ]

    detection_rows = [["Defect type", "Confidence", "Review", "Source"]]
    for detection in detail.detections:
        detection_rows.append(
            [
                detection.defect_type.value,
                f"{float(detection.confidence):.3f}",
                detection.review.value,
                detection.source.value,
            ]
        )
    story.append(Table(detection_rows, style=_TABLE_STYLE, hAlign="LEFT"))

    if detail.analysis is not None:
        story.append(Spacer(1, 0.5 * cm))
        story.append(Paragraph("Analysis", _HEADING))
        story.append(Paragraph(f"Severity: {detail.analysis.severity_max or '—'}", _BODY))
        if detail.analysis.executive_summary:
            story.append(Paragraph(detail.analysis.executive_summary, _BODY))
        for entry in detail.analysis.per_defect or []:
            story.append(Spacer(1, 0.2 * cm))
            story.append(Paragraph(f"<b>{entry.severity.value}</b> — {entry.description}", _BODY))
            if entry.probable_causes:
                story.append(Paragraph("Causes: " + "; ".join(entry.probable_causes), _BODY))
            if entry.suggested_solutions:
                story.append(Paragraph("Solutions: " + "; ".join(entry.suggested_solutions), _BODY))

    if detail.disposition is not None:
        story.append(Spacer(1, 0.5 * cm))
        story.append(Paragraph(f"Disposition: {detail.disposition.decision.value}", _HEADING))

    _doc(path).build(story)


def write_consolidated(rows: list[InspectionListItem], path: Path) -> None:
    story = [
        Paragraph("Consolidated Inspection Report", _TITLE),
        _generated_at_line(),
        Paragraph(f"{len(rows)} inspection(s) matched the applied filters.", _BODY),
        Spacer(1, 0.5 * cm),
    ]

    table_rows = [["Batch", "Board", "Status", "Defect types", "Severity", "Created"]]
    for item in rows:
        table_rows.append(
            [
                item.batch_number or "—",
                item.board_number or "—",
                item.status.value,
                ", ".join(dt.value for dt in item.defect_types) or "—",
                item.severity_max.value if item.severity_max else "—",
                item.created_at.strftime("%Y-%m-%d"),
            ]
        )
    story.append(Table(table_rows, style=_TABLE_STYLE, hAlign="LEFT", repeatRows=1))

    _doc(path).build(story)


def write_executive(
    *,
    summary: StatsSummary,
    by_defect_type: StatsByDefectType,
    top_batches: list[tuple[str, int]],
    date_from: datetime | None,
    date_to: datetime | None,
    path: Path,
) -> None:
    start = date_from.date() if date_from else "earliest"
    end = date_to.date() if date_to else "latest"
    period = f"{start} to {end}"
    story = [
        Paragraph("Executive Summary Report", _TITLE),
        _generated_at_line(),
        Paragraph(f"Period: {period}", _BODY),
        Spacer(1, 0.5 * cm),
        Paragraph("Summary", _HEADING),
    ]

    summary_rows = [
        ["Total inspected", str(summary.total_inspected)],
        ["Total with defects", str(summary.total_with_defects)],
        ["Quality rate", f"{summary.quality_rate:.2f}%"],
        ["Inspected in last 24h", str(summary.last_24h_count)],
        ["Analyses validated", str(summary.analyses_validated)],
        ["Analyses rejected", str(summary.analyses_rejected)],
        [
            "Analysis precision rate",
            f"{summary.analysis_precision_rate:.2f}%"
            if summary.analysis_precision_rate is not None
            else "—",
        ],
    ]
    story.append(Table(summary_rows, style=_TABLE_STYLE, hAlign="LEFT"))

    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Defects by type", _HEADING))
    defect_rows = [["Defect type", "Count"]]
    for entry in by_defect_type.counts:
        defect_rows.append([entry.defect_type.value, str(entry.count)])
    story.append(Table(defect_rows, style=_TABLE_STYLE, hAlign="LEFT"))

    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Top batches by defect count", _HEADING))
    if top_batches:
        batch_rows = [["Batch", "Defect count"]]
        batch_rows.extend([batch_number, str(count)] for batch_number, count in top_batches)
        story.append(Table(batch_rows, style=_TABLE_STYLE, hAlign="LEFT"))
    else:
        story.append(Paragraph("No batches with reported defects in this period.", _BODY))

    _doc(path).build(story)
