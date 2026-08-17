"""CSV writer (FR-11).

The old file was one row per board with a semicolon separated list of defect classes in a
cell, which meant the one thing a spreadsheet is for, sorting and pivoting by defect, was the
one thing it could not do. Rows are now one per *defect occurrence*: the board's identity and
decision repeat on each of its rows, and every occurrence carries its own class, confidence,
position, severity and the analysis text written for it, including what the operator is meant
to do about it. A board with no reported defect still gets exactly one row, so the file also
answers "which boards were inspected", not only "where were the defects".

Column headers follow the report's language, same as every other generated artefact.
"""

import csv
from collections.abc import Iterator
from pathlib import Path

from app.reports.dataset import BoardSection
from app.reports.document import ReportDocument
from app.reports.strings import ReportLanguage, format_position, label_enum, translate

_COLUMN_KEYS = [
    "col.batch",
    "col.board",
    "col.inspection_id",
    "col.status",
    "col.created_at",
    "col.processed_at",
    "col.occurrence",
    "col.defect_type",
    "col.confidence",
    "col.position",
    "col.review",
    "col.source",
    "col.severity",
    "col.description",
    "col.probable_causes",
    "col.suggested_solutions",
    "col.disposition_recommendation",
    "col.disposition",
    "col.review_status",
]


def header(language: ReportLanguage) -> list[str]:
    return [translate(language, key) for key in _COLUMN_KEYS]


def _board_columns(board: BoardSection, language: ReportLanguage) -> list[str]:
    return [
        board.batch_number or "",
        board.board_number or "",
        str(board.inspection_id),
        label_enum(language, board.status, fallback=""),
        board.created_at.isoformat(),
        board.processed_at.isoformat() if board.processed_at else "",
    ]


def _decision_columns(board: BoardSection, language: ReportLanguage) -> list[str]:
    return [
        label_enum(language, board.disposition_recommendation, fallback=""),
        label_enum(language, board.disposition, fallback=""),
        label_enum(language, board.review_status, fallback=""),
    ]


def rows(document: ReportDocument) -> Iterator[list[str]]:
    language = document.language
    for board in document.dataset.boards:
        if not board.occurrences:
            yield (
                _board_columns(board, language)
                + ["", "", "", "", "", "", "", "", "", ""]
                + _decision_columns(board, language)
            )
            continue
        for occurrence in board.occurrences:
            yield (
                _board_columns(board, language)
                + [
                    f"{occurrence.index}/{occurrence.total_on_board}",
                    label_enum(language, occurrence.defect_type),
                    f"{float(occurrence.confidence):.3f}",
                    format_position(language, occurrence.bbox),
                    label_enum(language, occurrence.review),
                    label_enum(language, occurrence.source),
                    label_enum(language, occurrence.severity, fallback=""),
                    occurrence.description or "",
                    "; ".join(occurrence.probable_causes),
                    "; ".join(occurrence.suggested_solutions),
                ]
                + _decision_columns(board, language)
            )


def write(document: ReportDocument, path: Path) -> int:
    """Returns the number of data rows written, which is what the `Report.row_count` the
    operator sees on the reports screen refers to.
    """
    written = 0
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(header(document.language))
        for row in rows(document):
            writer.writerow(row)
            written += 1
    return written
