"""What a report is *about*, loaded once and handed to every format generator.

The old generators each queried for whatever they happened to render, so the PDF and the CSV
could describe the same request differently and neither could say anything about the batch a
board belongs to. Everything a report can show is assembled here instead: the boards in scope
with their occurrences numbered and positioned, and the aggregate footprint of each defect
class over both the report's own scope and the whole batch behind it, which is the input the
frequency reasoning needs (one occurrence in a batch of 1000 boards and one on every board of
100 are the same row in a detections table and opposite conclusions in a report).

RN-07 as everywhere else: only `is_reported` detections on `COMPLETED` images count toward
any aggregate.

Loading is bulk, not per board: three queries cover the whole board set, so a 500 board batch
costs the same round trips as a single board report.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.chain import strip_dashes
from app.agents.prompts.v1 import position_phrase
from app.analyses.localization import LocalizedAnalysis, analysis_language, localize_analyses
from app.core.language import Language
from app.knowledge.defects import severity_from_defect_counts
from app.models import (
    Analysis,
    Batch,
    Board,
    BoardDisposition,
    Detection,
    InspectionImage,
)
from app.models.enums import (
    AnalysisReviewStatus,
    BoardDispositionDecision,
    DefectType,
    DetectionReview,
    DetectionSource,
    DispositionRecommendation,
    ImageStatus,
    Severity,
)


@dataclass(frozen=True)
class DefectOccurrence:
    """One reported detection on one board, numbered within that board so every passage of the
    report can name which occurrence it is talking about.
    """

    index: int
    total_on_board: int
    detection_id: uuid.UUID
    defect_type: DefectType
    confidence: Decimal
    review: DetectionReview
    source: DetectionSource
    # `position` is the English phrase the analysis prompts use, kept so the report narrative is
    # given exactly the wording the agents were; the generators render `bbox` in the report's
    # own language instead (`app.reports.strings.format_position`).
    position: str
    bbox: dict[str, float]
    severity: Severity | None = None
    description: str | None = None
    probable_causes: list[str] = field(default_factory=list)
    suggested_solutions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BoardSection:
    inspection_id: uuid.UUID
    batch_number: str | None
    board_number: str | None
    status: ImageStatus
    created_at: datetime
    processed_at: datetime | None
    occurrences: list[DefectOccurrence]
    executive_summary: str | None = None
    # Language the analysis prose above is actually in. Normally the report's own language
    # (`app.analyses.localization` translates on the way in), but a board whose analysis could
    # not be localized keeps its original wording, and the PDF says so rather than leaving the
    # reader to wonder (issue #50).
    analysis_language: Language | None = None
    severity_max: Severity | None = None
    review_status: AnalysisReviewStatus | None = None
    disposition_recommendation: DispositionRecommendation | None = None
    disposition: BoardDispositionDecision | None = None
    failure_reason: str | None = None

    @property
    def has_defects(self) -> bool:
        return len(self.occurrences) > 0


@dataclass(frozen=True)
class DefectClassStat:
    defect_type: DefectType
    occurrences: int
    boards_affected: int
    boards_total: int

    @property
    def share_of_boards(self) -> float:
        """0..1 share of the boards in this scope carrying at least one of this class."""
        if self.boards_total <= 0:
            return 0.0
        return self.boards_affected / self.boards_total

    @property
    def is_recurring(self) -> bool:
        """Whether the class shows up widely enough for a shared upstream cause to be worth
        raising at all. Two boards is the floor: a single affected board is by definition not
        a pattern no matter how small the batch.
        """
        return self.boards_affected >= 2 and self.share_of_boards >= 0.2


@dataclass(frozen=True)
class Analytics:
    boards_total: int
    boards_with_defects: int
    defect_total: int
    severity: Severity | None
    by_defect_class: list[DefectClassStat]
    severity_counts: dict[Severity, int] = field(default_factory=dict)
    disposition_counts: dict[BoardDispositionDecision, int] = field(default_factory=dict)
    boards_without_disposition: int = 0
    analyses_pending_review: int = 0

    @property
    def defect_rate(self) -> float:
        if self.boards_total <= 0:
            return 0.0
        return self.boards_with_defects / self.boards_total


@dataclass(frozen=True)
class ReportDataset:
    """Boards in scope plus the two aggregate views a report reasons over: `analytics` covers
    exactly the boards included, `batch_analytics` the entire batch they came from (`None`
    when the scope spans several batches or none). For a report over a whole batch the two
    describe the same set, which is exactly right: the frequency section then says the same
    thing either way.
    """

    boards: list[BoardSection]
    analytics: Analytics
    batch_number: str | None = None
    batch_analytics: Analytics | None = None

    @property
    def batch_view(self) -> Analytics:
        return self.batch_analytics or self.analytics

    @property
    def boards_with_defects(self) -> list[BoardSection]:
        return [board for board in self.boards if board.has_defects]


def _per_defect_index(localized: LocalizedAnalysis | None) -> dict[str, dict[str, Any]]:
    """The analysis' per-defect entries keyed by `detection_id` so each occurrence can pick up
    its own. Entries whose detection no longer exists (a detection re-reviewed as a false
    positive after the analysis ran) simply never get looked up.
    """
    return localized.by_detection_id if localized is not None else {}


def _localized_for(
    analysis: Analysis | None, localized_by_analysis: dict[uuid.UUID, LocalizedAnalysis]
) -> LocalizedAnalysis | None:
    """The localized view of `analysis`, or the analysis as stored when no localization ran
    (`language=None`) or it could not be produced for this board.
    """
    if analysis is None:
        return None
    localized = localized_by_analysis.get(analysis.id)
    if localized is not None:
        return localized
    return LocalizedAnalysis(
        language=analysis_language(analysis),
        per_defect=list(analysis.per_defect or []),
        executive_summary=analysis.executive_summary,
    )


def _severity_of(entry: dict[str, Any]) -> Severity | None:
    raw = entry.get("severity")
    try:
        return Severity(raw) if raw else None
    except ValueError:
        return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [strip_dashes(str(item)) for item in value if item]


def _text(value: Any) -> str | None:
    """Stored analysis prose on its way into a report. Dashes are stripped here rather than
    only at write time: the chain strips them from new analyses, and this covers rows written
    before it did, for every format at once.
    """
    if not value:
        return None
    return strip_dashes(str(value))


async def load_board_sections(
    db: AsyncSession, image_ids: list[uuid.UUID], *, language: Language | None = None
) -> dict[uuid.UUID, BoardSection]:
    """Every board in `image_ids` with its occurrences, analysis and decision, in three
    queries regardless of how many boards there are.

    `language` is the report's language: the stored analysis prose is localized into it
    (issue #50), baseline boards for free and agent-written ones through a cached translation.
    `None` keeps whatever the analyses were written in.
    """
    if not image_ids:
        return {}

    rows = (
        await db.execute(
            select(InspectionImage, Board, Batch, Analysis, BoardDisposition)
            .select_from(InspectionImage)
            .outerjoin(Board, InspectionImage.board_id == Board.id)
            .outerjoin(Batch, Board.batch_id == Batch.id)
            .outerjoin(Analysis, Analysis.image_id == InspectionImage.id)
            .outerjoin(BoardDisposition, BoardDisposition.image_id == InspectionImage.id)
            .where(InspectionImage.id.in_(image_ids))
        )
    ).all()

    detections_by_image: dict[uuid.UUID, list[Detection]] = defaultdict(list)
    detection_rows = (
        (
            await db.execute(
                select(Detection)
                .where(Detection.image_id.in_(image_ids), Detection.is_reported.is_(True))
                .order_by(Detection.image_id, Detection.id)
            )
        )
        .scalars()
        .all()
    )
    for detection in detection_rows:
        detections_by_image[detection.image_id].append(detection)

    localized_by_analysis: dict[uuid.UUID, LocalizedAnalysis] = {}
    if language is not None:
        localized_by_analysis = await localize_analyses(
            db,
            [row[3] for row in rows if row[3] is not None],
            language=language,
            detections_by_image=detections_by_image,
        )

    sections: dict[uuid.UUID, BoardSection] = {}
    for image, board, batch, analysis, disposition in rows:
        detections = detections_by_image.get(image.id, [])
        localized = _localized_for(analysis, localized_by_analysis)
        per_defect = _per_defect_index(localized)
        occurrences = []
        for index, detection in enumerate(detections, start=1):
            entry = per_defect.get(str(detection.id), {})
            occurrences.append(
                DefectOccurrence(
                    index=index,
                    total_on_board=len(detections),
                    detection_id=detection.id,
                    defect_type=detection.defect_type,
                    confidence=detection.confidence,
                    review=detection.review,
                    source=detection.source,
                    position=position_phrase(detection.bbox),
                    bbox=detection.bbox,
                    severity=_severity_of(entry),
                    description=_text(entry.get("description")),
                    probable_causes=_string_list(entry.get("probable_causes")),
                    suggested_solutions=_string_list(entry.get("suggested_solutions")),
                )
            )
        sections[image.id] = BoardSection(
            inspection_id=image.id,
            batch_number=batch.batch_number if batch is not None else None,
            board_number=board.board_number if board is not None else None,
            status=image.status,
            created_at=image.created_at,
            processed_at=image.processed_at,
            occurrences=occurrences,
            executive_summary=(
                _text(localized.executive_summary) if localized is not None else None
            ),
            analysis_language=localized.language if localized is not None else None,
            severity_max=analysis.severity_max if analysis is not None else None,
            review_status=analysis.review_status if analysis is not None else None,
            disposition_recommendation=(
                analysis.disposition_recommendation if analysis is not None else None
            ),
            disposition=disposition.decision if disposition is not None else None,
            failure_reason=image.failure_reason,
        )
    return sections


def analytics_from_sections(sections: list[BoardSection]) -> Analytics:
    """Aggregates over an already loaded board set, the report's own scope."""
    occurrences_by_class: dict[DefectType, int] = defaultdict(int)
    boards_by_class: dict[DefectType, set[uuid.UUID]] = defaultdict(set)
    severity_counts: dict[Severity, int] = defaultdict(int)
    disposition_counts: dict[BoardDispositionDecision, int] = defaultdict(int)
    boards_with_defects = 0
    boards_without_disposition = 0
    analyses_pending_review = 0

    for section in sections:
        if section.has_defects:
            boards_with_defects += 1
        for occurrence in section.occurrences:
            occurrences_by_class[occurrence.defect_type] += 1
            boards_by_class[occurrence.defect_type].add(section.inspection_id)
        if section.severity_max is not None:
            severity_counts[section.severity_max] += 1
        if section.disposition is not None:
            disposition_counts[section.disposition] += 1
        else:
            boards_without_disposition += 1
        if section.review_status is AnalysisReviewStatus.PENDING:
            analyses_pending_review += 1

    boards_total = len(sections)
    by_defect_class = [
        DefectClassStat(
            defect_type=defect_type,
            occurrences=count,
            boards_affected=len(boards_by_class[defect_type]),
            boards_total=boards_total,
        )
        for defect_type, count in sorted(
            occurrences_by_class.items(), key=lambda item: (-item[1], item[0].value)
        )
    ]

    return Analytics(
        boards_total=boards_total,
        boards_with_defects=boards_with_defects,
        defect_total=sum(occurrences_by_class.values()),
        severity=severity_from_defect_counts(
            occurrences_by_class,
            defect_rate=boards_with_defects / boards_total if boards_total else 0.0,
        ),
        by_defect_class=by_defect_class,
        severity_counts=dict(severity_counts),
        disposition_counts=dict(disposition_counts),
        boards_without_disposition=boards_without_disposition,
        analyses_pending_review=analyses_pending_review,
    )


def _scope_conditions(
    *,
    batch_number: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> list[Any]:
    conditions: list[Any] = [InspectionImage.status == ImageStatus.COMPLETED]
    if batch_number is not None:
        conditions.append(Batch.batch_number == batch_number)
    if date_from is not None:
        conditions.append(InspectionImage.created_at >= date_from)
    if date_to is not None:
        conditions.append(InspectionImage.created_at <= date_to)
    return conditions


async def scope_analytics(
    db: AsyncSession,
    *,
    batch_number: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> Analytics | None:
    """A whole batch's (or period's) footprint, counted in SQL rather than by loading every
    board: a batch report only details the boards it includes, but its frequency reasoning has
    to be able to say "on 3 of the 480 boards inspected in this batch", and an executive
    summary spans more boards than anyone would want materialised in memory.

    `None` when nothing completed in the scope, which the caller reads as "no batch view",
    never as an error.
    """
    conditions = _scope_conditions(
        batch_number=batch_number, date_from=date_from, date_to=date_to
    )
    boards_total = await db.scalar(
        select(func.count(InspectionImage.id))
        .select_from(InspectionImage)
        .outerjoin(Board, InspectionImage.board_id == Board.id)
        .outerjoin(Batch, Board.batch_id == Batch.id)
        .where(*conditions)
    )
    if not boards_total:
        return None

    defect_conditions = [*conditions, Detection.is_reported.is_(True)]
    rows = (
        await db.execute(
            select(
                Detection.defect_type,
                func.count(Detection.id),
                func.count(func.distinct(InspectionImage.id)),
            )
            .select_from(Detection)
            .join(InspectionImage, Detection.image_id == InspectionImage.id)
            .outerjoin(Board, InspectionImage.board_id == Board.id)
            .outerjoin(Batch, Board.batch_id == Batch.id)
            .where(*defect_conditions)
            .group_by(Detection.defect_type)
        )
    ).all()

    boards_with_defects = await db.scalar(
        select(func.count(func.distinct(InspectionImage.id)))
        .select_from(Detection)
        .join(InspectionImage, Detection.image_id == InspectionImage.id)
        .outerjoin(Board, InspectionImage.board_id == Board.id)
        .outerjoin(Batch, Board.batch_id == Batch.id)
        .where(*defect_conditions)
    )

    counts = {defect_type: int(count) for defect_type, count, _boards in rows}
    by_defect_class = [
        DefectClassStat(
            defect_type=defect_type,
            occurrences=int(count),
            boards_affected=int(boards),
            boards_total=int(boards_total),
        )
        for defect_type, count, boards in sorted(rows, key=lambda row: (-row[1], row[0].value))
    ]

    total_boards = int(boards_total)
    defective_boards = int(boards_with_defects or 0)
    return Analytics(
        boards_total=total_boards,
        boards_with_defects=defective_boards,
        defect_total=sum(counts.values()),
        severity=severity_from_defect_counts(
            counts, defect_rate=defective_boards / total_boards if total_boards else 0.0
        ),
        by_defect_class=by_defect_class,
    )


async def build_dataset(
    db: AsyncSession,
    image_ids: list[uuid.UUID],
    *,
    ordered_ids: list[uuid.UUID] | None = None,
    language: Language | None = None,
) -> ReportDataset:
    """`ordered_ids` preserves a caller's ordering (the inspections listing's, so a report and
    the screen it was requested from read in the same order); the loader itself is unordered.

    `language` is passed straight through to `load_board_sections`, which localizes the stored
    analysis prose into it.
    """
    sections_by_id = await load_board_sections(db, image_ids, language=language)
    order = ordered_ids or image_ids
    sections = [sections_by_id[image_id] for image_id in order if image_id in sections_by_id]

    batch_numbers = {section.batch_number for section in sections if section.batch_number}
    batch_number = next(iter(batch_numbers)) if len(batch_numbers) == 1 else None

    return ReportDataset(
        boards=sections,
        analytics=analytics_from_sections(sections),
        batch_number=batch_number,
        batch_analytics=(
            await scope_analytics(db, batch_number=batch_number)
            if batch_number is not None
            else None
        ),
    )


async def build_period_dataset(
    db: AsyncSession, *, date_from: datetime | None, date_to: datetime | None
) -> ReportDataset:
    """The executive summary's scope (FR-11): aggregates over a period, with no board list at
    all. A three month period can cover tens of thousands of boards and the executive report
    never prints one of them individually, so they are counted in SQL and never loaded.
    """
    analytics = await scope_analytics(db, date_from=date_from, date_to=date_to)
    return ReportDataset(
        boards=[],
        analytics=analytics or Analytics(0, 0, 0, None, []),
    )
