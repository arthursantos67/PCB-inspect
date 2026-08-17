"""One assembled report, ready to be written out in any format.

`app.reports.content` builds this; the PDF, CSV and XLSX writers consume it and never touch
the database themselves. That is what keeps the three formats describing the same request the
same way: the CSV's rows and the PDF's board sections come from the same `ReportDataset`, and
the PDF's opening prose is the narrative the CSV names in its own header block.
"""

from dataclasses import dataclass
from datetime import datetime

from app.models.enums import ReportType
from app.reports.dataset import ReportDataset
from app.reports.narrative import ReportNarrative
from app.reports.strings import ReportLanguage
from app.stats.schemas import StatsByDefectType, StatsSummary


@dataclass(frozen=True)
class ExecutiveFigures:
    """Only the executive summary report carries these: period aggregates that come from
    `app.stats.service` rather than from the boards themselves (FR-11).
    """

    summary: StatsSummary
    by_defect_type: StatsByDefectType
    top_batches: list[tuple[str, int]]


@dataclass(frozen=True)
class ReportDocument:
    type: ReportType
    language: ReportLanguage
    dataset: ReportDataset
    narrative: ReportNarrative
    generated_at: datetime
    date_from: datetime | None = None
    date_to: datetime | None = None
    board_number: str | None = None
    executive: ExecutiveFigures | None = None
