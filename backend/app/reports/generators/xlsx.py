"""XLSX writer for the consolidated report (FR-11) — same rows/columns as the CSV generator
(`app.reports.generators.csv`), just written with `openpyxl` instead of the stdlib `csv` module.
"""

from pathlib import Path

from openpyxl import Workbook

from app.inspections.schemas import InspectionListItem
from app.reports.generators.csv import _HEADER, _row


def write_consolidated(rows: list[InspectionListItem], path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Inspections"
    sheet.append(_HEADER)
    for item in rows:
        sheet.append(_row(item))
    workbook.save(path)
