"""PDF writer for every report type (FR-11).

What changed and why:

* The document now opens with an executive summary and a clickable table of contents, and
  every heading is also a PDF outline bookmark, so a batch report with dozens of boards can
  actually be navigated instead of scrolled.
* Each defect is printed as a numbered occurrence that names its class, its position on the
  board and the detector's confidence, so a paragraph can no longer be mistaken for a
  different detection on the same board.
* A frequency section reasons about how widely each class recurs across the whole batch, not
  just this board, which is the analysis the operator said the old PDF was missing entirely.
* All fixed wording comes from `app.reports.strings` in the requested language, and no dash
  characters are emitted anywhere: missing values print as "n/a" wording or a plain hyphen.

Layout is deliberately plain and typographic (one accent colour, ruled tables, generous
leading) rather than decorated. The visual redesign the user wants to research examples for
first is not attempted here.
"""

from collections.abc import Iterable, Sequence
from functools import partial
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

from app.models.enums import ReportType, Severity
from app.reports.dataset import BoardSection, DefectClassStat, DefectOccurrence
from app.reports.document import ReportDocument
from app.reports.strings import (
    ReportLanguage,
    format_decimal,
    format_percent,
    format_position,
    label_enum,
    translate,
)

# Beyond this many defective boards the per board sections stop and the document points at the
# CSV instead. A 400 board batch is a legitimate request; a 400 section PDF is not a document
# anyone reads, and the tabular formats exist for exactly that case.
MAX_DETAILED_BOARDS = 60

_INK = colors.HexColor("#111827")
_MUTED = colors.HexColor("#6b7280")
_ACCENT = colors.HexColor("#1d4ed8")
_RULE = colors.HexColor("#d1d5db")
_BAND = colors.HexColor("#f3f4f6")
_HEADER_BG = colors.HexColor("#1f2937")


_BASE = getSampleStyleSheet()

TITLE_STYLE = ParagraphStyle(
    "ReportTitle", parent=_BASE["Title"], fontSize=22, leading=26, alignment=0, textColor=_INK
)
SUBTITLE_STYLE = ParagraphStyle(
    "ReportSubtitle", parent=_BASE["Normal"], fontSize=11.5, leading=15, textColor=_MUTED
)
# Heading style *names* are the hook the document template uses to build the table of
# contents and the PDF outline, so they are matched by name in `_ReportDoc.afterFlowable`.
H1_STYLE = ParagraphStyle(
    "ReportH1",
    parent=_BASE["Heading1"],
    fontSize=14,
    leading=18,
    spaceBefore=16,
    spaceAfter=8,
    textColor=_INK,
)
H2_STYLE = ParagraphStyle(
    "ReportH2",
    parent=_BASE["Heading2"],
    fontSize=11.5,
    leading=15,
    spaceBefore=12,
    spaceAfter=6,
    textColor=_ACCENT,
)
H3_STYLE = ParagraphStyle(
    "ReportH3",
    parent=_BASE["Heading3"],
    fontSize=10,
    leading=13,
    spaceBefore=8,
    spaceAfter=3,
    textColor=_INK,
)
BODY_STYLE = ParagraphStyle(
    "ReportBody",
    parent=_BASE["BodyText"],
    fontSize=9.5,
    leading=13.5,
    alignment=TA_JUSTIFY,
    textColor=_INK,
)
SMALL_STYLE = ParagraphStyle(
    "ReportSmall", parent=BODY_STYLE, fontSize=8.5, leading=11.5, textColor=_MUTED
)
CELL_STYLE = ParagraphStyle(
    "ReportCell",
    parent=_BASE["BodyText"],
    fontSize=8,
    leading=10.5,
    alignment=0,
    spaceAfter=0,
    textColor=_INK,
)
# Every cell in these tables is a `Paragraph`, and a `TableStyle` TEXTCOLOR/FONTNAME command
# does not reach text drawn inside a flowable: the paragraph's own style wins. So the header
# row needs its ink and its weight set here, not in `_TABLE_STYLE`, or it renders near black on
# the dark header band and the column titles are unreadable.
HEADER_CELL_STYLE = ParagraphStyle(
    "ReportHeaderCell", parent=CELL_STYLE, fontName="Helvetica-Bold", textColor=colors.white
)
# Same reason: the muted key column of a key/value table.
KEY_CELL_STYLE = ParagraphStyle("ReportKeyCell", parent=CELL_STYLE, textColor=_MUTED)

_TABLE_STYLE = TableStyle(
    [
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 10.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, _RULE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _BAND]),
    ]
)

_KEY_VALUE_STYLE = TableStyle(
    [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEADING", (0, 0), (-1, -1), 12),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
    ]
)


def _esc(value: object) -> str:
    return escape(str(value))


def _para(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_esc(text), style)


def _cell(text: str, style: ParagraphStyle = CELL_STYLE) -> Paragraph:
    return Paragraph(_esc(text), style)


def _dash(language: ReportLanguage) -> str:
    return translate(language, "note.not_available")


class _NumberedCanvas(pdf_canvas.Canvas):  # type: ignore[misc]  # reportlab ships no type stubs
    """Two pass page numbering: pages are buffered so the footer can print "page 3 of 17"
    rather than an open ended "page 3", which is what makes a printed report checkable.
    """

    def __init__(self, *args: Any, footer_template: str = "{page}/{total}", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._footer_template = footer_template
        self._saved_states: list[dict[str, Any]] = []

    def showPage(self) -> None:  # noqa: N802 (reportlab's API spelling)
        self._saved_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved_states)
        for state in self._saved_states:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total: int) -> None:
        self.saveState()
        self.setFont("Helvetica", 7.5)
        self.setFillColor(_MUTED)
        width, _height = self._pagesize
        self.setStrokeColor(_RULE)
        self.line(1.7 * cm, 1.35 * cm, width - 1.7 * cm, 1.35 * cm)
        self.drawRightString(
            width - 1.7 * cm,
            1.0 * cm,
            self._footer_template.format(page=self._pageNumber, total=total),
        )
        self.restoreState()


class _ReportDoc(SimpleDocTemplate):  # type: ignore[misc]  # reportlab ships no type stubs
    """Turns every H1/H2 paragraph into a table of contents entry and a PDF outline bookmark
    (the "no navigation within the document" problem).
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._bookmark_seq = 0

    def build(self, *args: Any, **kwargs: Any) -> Any:
        """`multiBuild` lays the document out repeatedly until the table of contents stops
        changing, and it compares each pass's entries with the previous pass's. The bookmark
        key is part of an entry, so the counter has to restart with every pass: letting it run
        on across passes makes every entry differ from the last one and the build never
        converges, failing with "Index entries not resolved".
        """
        self._bookmark_seq = 0
        return super().build(*args, **kwargs)

    def afterFlowable(self, flowable: Any) -> None:  # noqa: N802 (reportlab's API spelling)
        if not isinstance(flowable, Paragraph):
            return
        level = {"ReportH1": 0, "ReportH2": 1}.get(flowable.style.name)
        if level is None:
            return
        text = flowable.getPlainText()
        self._bookmark_seq += 1
        key = f"sec-{self._bookmark_seq}"
        self.canv.bookmarkPage(key)
        # `key` has to stay a `str` here. reportlab maps destination name to bookmark title in
        # `addOutlineEntry` and reads that map back in `setNames` after decoding the name to
        # `str`, so a `bytes` key stores the title under a key the lookup never finds and every
        # bookmark silently falls back to showing "sec-1", "sec-2" instead of its heading.
        self.canv.addOutlineEntry(text, key, level=level, closed=(level == 0))
        self.notify("TOCEntry", (level, text, self.page, key))


def _heading(text: str, style: ParagraphStyle) -> Paragraph:
    return _para(text, style)


def _key_value_table(pairs: Sequence[tuple[str, str]], width: float = 17.0) -> Table:
    rows = [[_cell(key, KEY_CELL_STYLE), _cell(value)] for key, value in pairs]
    table = Table(rows, colWidths=[width * 0.33 * cm, width * 0.67 * cm], hAlign="LEFT")
    table.setStyle(_KEY_VALUE_STYLE)
    return table


def _data_table(
    header: Sequence[str], rows: Iterable[Sequence[str]], widths: Sequence[float]
) -> Table:
    data = [[_cell(column, HEADER_CELL_STYLE) for column in header]]
    data.extend([_cell(value) for value in row] for row in rows)
    table = Table(data, colWidths=[width * cm for width in widths], hAlign="LEFT", repeatRows=1)
    table.setStyle(_TABLE_STYLE)
    return table


def _severity_chip(language: ReportLanguage, severity: Severity | None) -> str:
    if severity is None:
        return _dash(language)
    return label_enum(language, severity)


def _title(document: ReportDocument) -> str:
    return translate(document.language, f"title.{document.type.value}")


def _scope_line(document: ReportDocument) -> str:
    language = document.language
    dataset = document.dataset
    if document.type is ReportType.INDIVIDUAL and dataset.boards:
        board = dataset.boards[0]
        return translate(
            language,
            "scope.board",
            batch=board.batch_number or _dash(language),
            board=board.board_number or _dash(language),
        )
    if dataset.batch_number:
        return translate(language, "scope.batch", batch=dataset.batch_number)
    return translate(language, "scope.all")


def _period_line(document: ReportDocument) -> str:
    language = document.language
    if document.date_from is None and document.date_to is None:
        return translate(language, "period.all_time")
    start = (
        document.date_from.date().isoformat()
        if document.date_from
        else translate(language, "period.earliest")
    )
    end = (
        document.date_to.date().isoformat()
        if document.date_to
        else translate(language, "period.latest")
    )
    return translate(language, "period.range", start=start, end=end)


def _cover(document: ReportDocument) -> list[Any]:
    language = document.language
    narrative_source = translate(
        language,
        "meta.narrative_llm" if document.narrative.written_by_model else "meta.narrative_computed",
    )
    pairs = [
        (translate(language, "meta.scope"), _scope_line(document)),
        (translate(language, "meta.period"), _period_line(document)),
        (
            translate(language, "meta.boards_in_report"),
            str(document.dataset.analytics.boards_total),
        ),
        (
            translate(language, "meta.generated_at"),
            document.generated_at.strftime("%Y-%m-%d %H:%M"),
        ),
        (translate(language, "meta.narrative_source"), narrative_source),
    ]
    return [
        _para(_title(document), TITLE_STYLE),
        Spacer(1, 0.2 * cm),
        _para(_scope_line(document), SUBTITLE_STYLE),
        Spacer(1, 0.35 * cm),
        HRFlowable(width="100%", thickness=1, color=_RULE, spaceAfter=10),
        _key_value_table(pairs),
        Spacer(1, 0.4 * cm),
    ]


def _toc() -> list[Any]:
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle("TOC0", fontName="Helvetica-Bold", fontSize=9.5, leading=15, textColor=_INK),
        ParagraphStyle(
            "TOC1", fontName="Helvetica", fontSize=9, leading=13, leftIndent=14, textColor=_MUTED
        ),
    ]
    return [toc]


def _summary_section(document: ReportDocument) -> list[Any]:
    language = document.language
    story: list[Any] = [
        _heading(translate(language, "section.summary"), H1_STYLE),
        _para(document.narrative.overview, BODY_STYLE),
    ]

    analytics = document.dataset.analytics
    figures: list[tuple[str, str]] = [
        (translate(language, "kpi.boards_inspected"), str(analytics.boards_total)),
        (translate(language, "kpi.boards_with_defects"), str(analytics.boards_with_defects)),
        (
            translate(language, "kpi.defect_rate"),
            format_percent(analytics.defect_rate, language),
        ),
        (translate(language, "kpi.total_defects"), str(analytics.defect_total)),
        (
            translate(language, "kpi.aggregated_severity"),
            _severity_chip(language, analytics.severity),
        ),
        (translate(language, "kpi.defect_classes"), str(len(analytics.by_defect_class))),
    ]
    if document.executive is not None:
        summary = document.executive.summary
        figures = [
            (translate(language, "kpi.total_inspected"), str(summary.total_inspected)),
            (
                translate(language, "kpi.boards_with_defects"),
                str(summary.total_with_defects),
            ),
            (
                translate(language, "kpi.quality_rate"),
                format_decimal(summary.quality_rate, language) + "%",
            ),
            (translate(language, "kpi.last_24h"), str(summary.last_24h_count)),
            (translate(language, "kpi.analyses_validated"), str(summary.analyses_validated)),
            (translate(language, "kpi.analyses_rejected"), str(summary.analyses_rejected)),
            (
                translate(language, "kpi.precision_rate"),
                format_decimal(summary.analysis_precision_rate, language) + "%"
                if summary.analysis_precision_rate is not None
                else _dash(language),
            ),
        ]

    story.append(Spacer(1, 0.3 * cm))
    story.append(_heading(translate(language, "section.kpis"), H2_STYLE))
    story.append(
        _data_table(
            [translate(language, "col.metric"), translate(language, "col.value")],
            [[label, value] for label, value in figures],
            [9.0, 8.0],
        )
    )
    return story


def _frequency_section(document: ReportDocument) -> list[Any]:
    language = document.language
    analytics = document.dataset.batch_view
    key = "section.frequency" if document.dataset.batch_number else "section.frequency_period"
    story: list[Any] = [_heading(translate(language, key), H1_STYLE)]

    stats: list[DefectClassStat] = analytics.by_defect_class
    if not stats:
        story.append(_para(translate(language, "note.no_defects"), BODY_STYLE))
        return story

    story.append(
        _data_table(
            [
                translate(language, "col.defect_type"),
                translate(language, "col.occurrences"),
                translate(language, "col.boards_affected"),
                translate(language, "col.share_of_boards"),
            ],
            [
                [
                    label_enum(language, stat.defect_type),
                    str(stat.occurrences),
                    f"{stat.boards_affected}/{stat.boards_total}",
                    format_percent(stat.share_of_boards, language),
                ]
                for stat in stats
            ],
            [6.0, 3.0, 4.0, 4.0],
        )
    )

    for stat in stats:
        note = document.narrative.note_for(stat.defect_type)
        if not note:
            continue
        story.append(Spacer(1, 0.25 * cm))
        story.append(
            KeepTogether(
                [
                    _heading(label_enum(language, stat.defect_type).capitalize(), H3_STYLE),
                    _para(note, BODY_STYLE),
                ]
            )
        )
    return story


def _board_overview_table(document: ReportDocument) -> list[Any]:
    language = document.language
    boards = document.dataset.boards
    rows = []
    for board in boards:
        defects = ", ".join(
            sorted({label_enum(language, o.defect_type) for o in board.occurrences})
        )
        rows.append(
            [
                board.board_number or _dash(language),
                str(len(board.occurrences)),
                defects or _dash(language),
                _severity_chip(language, board.severity_max),
                label_enum(language, board.disposition, fallback=_dash(language)),
                board.created_at.strftime("%Y-%m-%d %H:%M"),
            ]
        )
    return [
        _heading(translate(language, "section.board_overview"), H1_STYLE),
        _data_table(
            [
                translate(language, "col.board"),
                translate(language, "col.defects"),
                translate(language, "col.defect_type"),
                translate(language, "col.severity"),
                translate(language, "col.disposition"),
                translate(language, "col.created_at"),
            ],
            rows,
            [3.2, 1.8, 5.0, 2.2, 2.6, 2.2],
        ),
    ]


def _occurrence_block(language: ReportLanguage, occurrence: DefectOccurrence) -> list[Any]:
    heading = translate(
        language,
        "occurrence.heading",
        index=occurrence.index,
        total=occurrence.total_on_board,
        defect=label_enum(language, occurrence.defect_type),
        position=format_position(language, occurrence.bbox),
    )
    block: list[Any] = [_heading(heading, H3_STYLE)]
    facts = (
        f"{translate(language, 'label.confidence')}: "
        f"{format_decimal(float(occurrence.confidence), language, places=2)} | "
        f"{translate(language, 'label.severity')}: "
        f"{_severity_chip(language, occurrence.severity)} | "
        f"{translate(language, 'col.review')}: {label_enum(language, occurrence.review)} | "
        f"{translate(language, 'col.source')}: {label_enum(language, occurrence.source)}"
    )
    block.append(_para(facts, SMALL_STYLE))
    if occurrence.description:
        block.append(_para(occurrence.description, BODY_STYLE))
    else:
        block.append(_para(translate(language, "occurrence.no_analysis"), SMALL_STYLE))
    if occurrence.probable_causes:
        block.append(
            _para(
                f"{translate(language, 'label.causes')}: " + "; ".join(occurrence.probable_causes),
                BODY_STYLE,
            )
        )
    if occurrence.suggested_solutions:
        block.append(
            _para(
                f"{translate(language, 'label.solutions')}: "
                + "; ".join(occurrence.suggested_solutions),
                BODY_STYLE,
            )
        )
    return block


def _board_section(document: ReportDocument, board: BoardSection) -> list[Any]:
    language = document.language
    title = f"{translate(language, 'meta.board')} {board.board_number or _dash(language)}"
    if document.type is not ReportType.INDIVIDUAL and board.batch_number:
        title = f"{title} ({translate(language, 'meta.batch')} {board.batch_number})"

    story: list[Any] = [_heading(title, H2_STYLE)]
    story.append(
        _key_value_table(
            [
                (translate(language, "col.status"), label_enum(language, board.status)),
                (
                    translate(language, "col.created_at"),
                    board.created_at.strftime("%Y-%m-%d %H:%M"),
                ),
                (
                    translate(language, "col.severity"),
                    _severity_chip(language, board.severity_max),
                ),
                (
                    translate(language, "col.disposition_recommendation"),
                    label_enum(
                        language, board.disposition_recommendation, fallback=_dash(language)
                    ),
                ),
                (
                    translate(language, "col.disposition"),
                    label_enum(language, board.disposition, fallback=_dash(language)),
                ),
                (
                    translate(language, "col.review_status"),
                    label_enum(language, board.review_status, fallback=_dash(language)),
                ),
            ]
        )
    )

    # A board whose analysis could not be translated (no analysis model reachable when the
    # report ran) keeps its original wording rather than being left out, and says so once, at
    # the top of the board, instead of leaving the reader to work out why one section is in
    # another language (issue #50).
    if board.analysis_language is not None and board.analysis_language is not language:
        story.append(Spacer(1, 0.2 * cm))
        story.append(
            _para(
                translate(
                    language,
                    "note.analysis_not_translated",
                    written_in=translate(language, f"language.{board.analysis_language.value}"),
                ),
                SMALL_STYLE,
            )
        )

    if board.executive_summary:
        story.append(Spacer(1, 0.2 * cm))
        story.append(_heading(translate(language, "label.board_analysis"), H3_STYLE))
        story.append(_para(board.executive_summary, BODY_STYLE))

    if board.occurrences:
        story.append(Spacer(1, 0.25 * cm))
        story.append(_heading(translate(language, "section.detections"), H3_STYLE))
        story.append(
            _data_table(
                [
                    translate(language, "col.occurrence"),
                    translate(language, "col.defect_type"),
                    translate(language, "col.confidence"),
                    translate(language, "col.review"),
                    translate(language, "col.source"),
                    translate(language, "col.position"),
                ],
                [
                    [
                        str(occurrence.index),
                        label_enum(language, occurrence.defect_type),
                        format_decimal(float(occurrence.confidence), language, places=3),
                        label_enum(language, occurrence.review),
                        label_enum(language, occurrence.source),
                        format_position(language, occurrence.bbox),
                    ]
                    for occurrence in board.occurrences
                ],
                [2.0, 3.0, 2.0, 2.4, 1.8, 5.8],
            )
        )
        story.append(Spacer(1, 0.25 * cm))
        story.append(_heading(translate(language, "section.analysis"), H3_STYLE))
        for occurrence in board.occurrences:
            story.append(KeepTogether(_occurrence_block(language, occurrence)))
            story.append(Spacer(1, 0.15 * cm))
    else:
        story.append(Spacer(1, 0.2 * cm))
        story.append(_para(translate(language, "note.no_defects"), SMALL_STYLE))

    return story


def _boards_section(document: ReportDocument) -> list[Any]:
    language = document.language
    dataset = document.dataset
    if not dataset.boards:
        return [
            _heading(translate(language, "section.boards"), H1_STYLE),
            _para(translate(language, "note.no_boards"), BODY_STYLE),
        ]

    story: list[Any] = []
    if document.type is not ReportType.INDIVIDUAL:
        story.extend(_board_overview_table(document))
        detailed = dataset.boards_with_defects
        clean = len(dataset.boards) - len(detailed)
        if clean:
            story.append(Spacer(1, 0.2 * cm))
            story.append(
                _para(translate(language, "note.boards_without_defects", count=clean), SMALL_STYLE)
            )
    else:
        detailed = dataset.boards

    story.append(PageBreak())
    story.append(_heading(translate(language, "section.boards"), H1_STYLE))
    if not detailed:
        story.append(_para(translate(language, "note.no_defects"), BODY_STYLE))
        return story

    shown = detailed[:MAX_DETAILED_BOARDS]
    if len(detailed) > len(shown):
        story.append(
            _para(
                translate(
                    language,
                    "note.detail_truncated",
                    shown=len(shown),
                    total=len(detailed),
                ),
                SMALL_STYLE,
            )
        )
    for board in shown:
        story.extend(_board_section(document, board))
        story.append(Spacer(1, 0.3 * cm))
    return story


def _top_batches_section(document: ReportDocument) -> list[Any]:
    language = document.language
    figures = document.executive
    if figures is None:
        return []
    story: list[Any] = [_heading(translate(language, "section.top_batches"), H1_STYLE)]
    if not figures.top_batches:
        story.append(_para(translate(language, "note.no_defects"), BODY_STYLE))
        return story
    story.append(
        _data_table(
            [translate(language, "col.batch"), translate(language, "col.count")],
            [[batch_number, str(count)] for batch_number, count in figures.top_batches],
            [10.0, 5.0],
        )
    )
    return story


def _recommendations_section(document: ReportDocument) -> list[Any]:
    language = document.language
    story: list[Any] = [_heading(translate(language, "section.recommendations"), H1_STYLE)]
    recommendations = document.narrative.recommendations
    if not recommendations:
        story.append(_para(translate(language, "note.no_recommendations"), BODY_STYLE))
        return story
    for index, item in enumerate(recommendations, start=1):
        story.append(_para(f"{index}. {item}", BODY_STYLE))
    return story


def _story(document: ReportDocument) -> list[Any]:
    story: list[Any] = []
    story.extend(_cover(document))
    story.append(_heading(translate(document.language, "toc.title"), H1_STYLE))
    story.extend(_toc())
    story.append(PageBreak())
    story.extend(_summary_section(document))
    story.extend(_frequency_section(document))
    if document.type is ReportType.EXECUTIVE:
        story.extend(_top_batches_section(document))
    else:
        story.extend(_boards_section(document))
    story.extend(_recommendations_section(document))
    return story


def write(document: ReportDocument, path: Path) -> None:
    """Renders `document` to `path`. Built twice (`multiBuild`) so the table of contents knows
    the final page numbers, then a third pass over the buffered pages numbers the footers.
    """
    doc = _ReportDoc(
        str(path),
        pagesize=A4,
        topMargin=1.7 * cm,
        bottomMargin=1.9 * cm,
        leftMargin=1.7 * cm,
        rightMargin=1.7 * cm,
        title=_title(document),
        author="PCB-Inspect",
        subject=_scope_line(document),
    )
    footer_template = translate(document.language, "footer.page", page="{page}", total="{total}")
    doc.multiBuild(
        _story(document),
        canvasmaker=partial(_NumberedCanvas, footer_template=footer_template),
    )
