"""CSV writer for the consolidated report (FR-11) — one row per `InspectionListItem`, the
exact shape `GET /api/v1/inspections` returns for the same filters (Issue 8), so the report's
columns can never drift from what the search screen already shows.
"""

import csv
from pathlib import Path

from app.inspections.schemas import InspectionListItem

_HEADER = [
    "id",
    "status",
    "batch_number",
    "board_number",
    "defect_types",
    "severity_max",
    "review_status",
    "disposition_recommendation",
    "disposition",
    "failure_reason",
    "created_at",
    "processed_at",
]


def _row(item: InspectionListItem) -> list[str]:
    return [
        str(item.id),
        item.status.value,
        item.batch_number or "",
        item.board_number or "",
        ";".join(defect_type.value for defect_type in item.defect_types),
        item.severity_max.value if item.severity_max else "",
        item.review_status.value if item.review_status else "",
        item.disposition_recommendation.value if item.disposition_recommendation else "",
        item.disposition.value if item.disposition else "",
        item.failure_reason or "",
        item.created_at.isoformat(),
        item.processed_at.isoformat() if item.processed_at else "",
    ]


def write_consolidated(rows: list[InspectionListItem], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(_HEADER)
        for item in rows:
            writer.writerow(_row(item))
