"""The analytical prose a report opens with.

What made the old PDF close to useless was that it had nothing to say: it printed the per
board analysis the agents had written and stopped there, so every occurrence of the same
defect class read identically and nothing ever weighed one board against the batch around it.
This module writes that missing layer, once per report rather than once per board: an
overview of what the scope actually shows, one note per defect class that reasons about how
widely the class recurs, and the actions the numbers support.

Two sources, one shape. When an analysis model is configured (`app.agents.llm_client`, the
same client the analysis chain and the chat use) it gets the counts as facts and writes the
prose in the requested language. When it is not reachable, or answers with something
unusable, the same figures are rendered through the templates in `app.reports.strings`. The
report never fails over narrative: an unreachable model degrades the wording, not the
document, which is the same contract `app.agents.chain` has with the baseline analysis.

The synthesis is not written from counts alone. The analyses already recorded in the database
for the boards in scope go into the prompt too (`_recorded_analysis`): the per board summaries
and, per defect class, the descriptions, probable causes and suggested solutions the agent
chain wrote when each board was inspected. The report is then a synthesis of conclusions the
system already reached rather than a second, unrelated opinion over the same rows, and where
those recorded texts repeat across boards the repetition itself is handed over as a count,
which is a signal about how uniform the analyses were.

The model is given numbers and recorded text, and asked to interpret them. It is never given
room to invent either: every figure it may cite is in the prompt, the frequency rule is
spelled out as evidence rather than proof, and anything it returns that does not parse is
discarded wholesale in favour of the computed text.
"""

import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.chain import strip_dashes
from app.agents.llm_client import LLMClient, LLMUnavailableError, build_llm_client
from app.knowledge.defects import DEFECT_KNOWLEDGE_BASE
from app.models.enums import DefectType
from app.reports.dataset import DefectClassStat, DefectOccurrence, ReportDataset
from app.reports.strings import (
    ReportLanguage,
    format_percent,
    label_enum,
    translate,
)

logger = logging.getLogger(__name__)

_LANGUAGE_NAME = {
    ReportLanguage.EN: "English",
    ReportLanguage.PT: "Brazilian Portuguese",
}

# Enough to say something useful about a scope without turning the summary into the report.
_MAX_RECOMMENDATIONS = 6

# Caps on the recorded analysis handed to the model. A 500 board batch holds far more written
# text than any prompt can carry, and most of it repeats: deduplicating first and then keeping
# the most frequent entries means the cap bites on variety, which is what the synthesis needs,
# rather than on volume.
_MAX_BOARD_SUMMARIES = 8
_MAX_ENTRIES_PER_CLASS = 5
_MAX_TEXT_CHARS = 400


@dataclass(frozen=True)
class ReportNarrative:
    overview: str
    defect_notes: dict[DefectType, str] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    written_by_model: bool = False

    def note_for(self, defect_type: DefectType) -> str | None:
        return self.defect_notes.get(defect_type)


class _DefectNote(BaseModel):
    defect_type: str
    note: str


class _NarrativeOutput(BaseModel):
    overview: str
    defect_notes: list[_DefectNote] = []
    recommendations: list[str] = []


def _trim(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= _MAX_TEXT_CHARS:
        return collapsed
    return collapsed[:_MAX_TEXT_CHARS].rstrip() + "..."


def _tally(values: Iterable[str | None]) -> list[tuple[str, int]]:
    """Distinct texts, most repeated first, each with the number of times it was recorded.

    Agent analyses of the same defect class often come out near identical across boards, which
    is exactly the repetition the report is supposed to stop reprinting. Collapsing them here
    keeps the prompt short and turns the repetition into information: "recorded on 14 boards"
    tells the model the reading was uniform, which one copy of the text alone does not.
    """
    counts: dict[str, int] = defaultdict(int)
    originals: dict[str, str] = {}
    for value in values:
        if not value:
            continue
        text = _trim(value)
        key = text.casefold()
        counts[key] += 1
        originals.setdefault(key, text)
    return [
        (originals[key], count)
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _tallied_line(label: str, values: Iterable[str | None]) -> str | None:
    entries = _tally(values)
    if not entries:
        return None
    rendered = "; ".join(
        f"{text} (recorded {count} times)" if count > 1 else text
        for text, count in entries[:_MAX_ENTRIES_PER_CLASS]
    )
    return f"  {label}: {rendered}"


def _recorded_analysis(dataset: ReportDataset) -> list[str]:
    """What the system already concluded about these boards, as prompt facts.

    Everything here was written by the analysis chain when each board was inspected and is
    already printed board by board in the report; giving it to the model as well is what makes
    the report's own summary a synthesis of those analyses instead of a separate opinion.
    """
    if not dataset.boards:
        return []

    lines = [
        "Analyses already recorded in the system for these boards, written when each board was "
        "inspected. Identical texts are collapsed into one entry carrying how many times they "
        "were recorded.",
    ]

    summaries = _tally(board.executive_summary for board in dataset.boards)
    if summaries:
        lines.append("Recorded board summaries:")
        for text, count in summaries[:_MAX_BOARD_SUMMARIES]:
            suffix = f" (recorded on {count} boards)" if count > 1 else ""
            lines.append(f"- {text}{suffix}")

    by_class: dict[DefectType, list[DefectOccurrence]] = defaultdict(list)
    for board in dataset.boards:
        for occurrence in board.occurrences:
            by_class[occurrence.defect_type].append(occurrence)

    for defect_type, occurrences in sorted(
        by_class.items(), key=lambda item: (-len(item[1]), item[0].value)
    ):
        lines.append(
            f"Recorded analysis for {defect_type.value}, over the "
            f"{len(occurrences)} occurrence(s) in this report's scope:"
        )
        lines.extend(
            line
            for line in (
                _tallied_line("what was observed", (item.description for item in occurrences)),
                _tallied_line(
                    "probable causes recorded",
                    (cause for item in occurrences for cause in item.probable_causes),
                ),
                _tallied_line(
                    "solutions recorded",
                    (solution for item in occurrences for solution in item.suggested_solutions),
                ),
            )
            if line is not None
        )

    return lines


def _facts(dataset: ReportDataset, *, language: ReportLanguage) -> str:
    scope = dataset.analytics
    batch = dataset.batch_view
    lines = [
        f"Report scope: {scope.boards_total} board(s) included"
        + (f", all from batch {dataset.batch_number}." if dataset.batch_number else "."),
        f"Of the boards included, {scope.boards_with_defects} carry at least one reported "
        f"defect ({scope.defect_rate * 100:.1f}%), {scope.defect_total} occurrence(s) in "
        f"total. Aggregated severity of the scope: "
        f"{scope.severity.value if scope.severity else 'none'}.",
    ]

    if scope.severity_counts:
        lines.append(
            "Boards by worst severity recorded: "
            + ", ".join(
                f"{severity.value}={count}" for severity, count in scope.severity_counts.items()
            )
            + "."
        )
    if scope.boards_without_disposition:
        lines.append(
            f"{scope.boards_without_disposition} board(s) have no operator decision recorded yet."
        )
    if scope.analyses_pending_review:
        lines.append(f"{scope.analyses_pending_review} analysis/analyses await operator review.")

    if batch is not scope and dataset.batch_number:
        lines.append(
            f"The batch {dataset.batch_number} as a whole has {batch.boards_total} completed "
            f"board(s), {batch.boards_with_defects} of them with defects, "
            f"{batch.defect_total} occurrence(s)."
        )

    lines.append(
        "Defect classes, counted over the whole batch when one batch is in scope "
        "(occurrences, boards affected, boards inspected):"
    )
    if batch.by_defect_class:
        for stat in batch.by_defect_class:
            knowledge = DEFECT_KNOWLEDGE_BASE[stat.defect_type]
            lines.append(
                f"- {stat.defect_type.value}: {stat.occurrences} occurrence(s) on "
                f"{stat.boards_affected} of {stat.boards_total} board(s) "
                f"({stat.share_of_boards * 100:.1f}% of the boards), reference severity "
                f"{knowledge.severity.value}, reference description: {knowledge.description}"
            )
    else:
        lines.append("- none")

    if len(dataset.boards) == 1:
        board = dataset.boards[0]
        lines.append(
            f"This report covers a single board, {board.board_number or 'unknown'}, with "
            f"{len(board.occurrences)} reported occurrence(s):"
        )
        for occurrence in board.occurrences:
            lines.append(
                f"- occurrence {occurrence.index}: {occurrence.defect_type.value} at the "
                f"{occurrence.position}, detector confidence {float(occurrence.confidence):.2f}, "
                f"severity {occurrence.severity.value if occurrence.severity else 'unrecorded'}"
            )

    lines.extend(_recorded_analysis(dataset))

    lines.append(f"Write every field in {_LANGUAGE_NAME[language]}.")
    return "\n".join(lines)


def _system_prompt(language: ReportLanguage, defect_classes: list[str]) -> str:
    classes = ", ".join(defect_classes) or "none"
    return (
        "You write the analytical section of a printed PCB inspection report that a quality "
        "engineer reads on the production line. You are given the counts the inspection "
        "system recorded. Interpret them: say what the scope shows, what the spread of each "
        "defect class across the boards suggests, and what should be done next. "
        "You are also given the analyses the system already recorded for these boards, written "
        "when each board was inspected: the board summaries and, per defect class, what was "
        "observed, the probable causes and the solutions already proposed. Those analyses are "
        "the record of what has already been concluded here. Synthesise them: carry their "
        "substance into your text, weigh it against the counts, and never contradict them or "
        "introduce a cause or a corrective action they do not raise unless the counts plainly "
        "support it. They may be written in another language than the one you must write in, "
        "so convey what they say in the requested language rather than copying them word for "
        "word, and never repeat a recorded text the report already prints board by board. "
        "Use only the figures given to you and never invent a number, a board, a defect class "
        "outside this list, a date or a cause the counts do not support. "
        "Frequency is your main tool: a class seen on one board out of many reads as an "
        "isolated occurrence and points at that board, while a class recurring on a large "
        "share of the boards points at something shared upstream, a stencil, a paste "
        "deposition step, a placement program, handling. Frequency is evidence and not proof, "
        "so state the reading as a possibility, keep the simpler local explanation on the "
        "table, and never assert a systemic cause the counts do not support. "
        "Be concrete and quantitative, cite the actual counts and shares, and never write a "
        "sentence that would be equally true of any other batch. "
        "Never use em dashes or en dashes. Use a comma, a colon or a separate sentence. "
        f"Write everything in {_LANGUAGE_NAME[language]}. "
        "The one exception is the defect class names, which are never translated in any "
        "language: missing_hole, mouse_bite, open_circuit, short, spur and spurious_copper are "
        "the names the detector and the dataset use, and the tables in this same report print "
        "them unchanged. Write them inside a Portuguese sentence exactly as you would inside "
        'an English one, so the prose and the tables name the same thing: "3 defeitos short", '
        'never "3 curtos"; "a classe missing_hole", never "a classe furo ausente". '
        "Respond with a single JSON object only, no prose and no markdown fences. Shape: "
        '{"overview": str, "defect_notes": [{"defect_type": str, "note": str}], '
        '"recommendations": [str]}. '
        f"overview is 3 to 6 sentences. defect_notes carries one entry per defect class among: "
        f"{classes}, each note 2 to 4 sentences naming the class's counts. recommendations "
        "carries 2 to 5 short imperative actions, and any defect class an action names is "
        "written with its untranslated name there too."
    )


def _computed_narrative(dataset: ReportDataset, language: ReportLanguage) -> ReportNarrative:
    """The same reading, rendered from templates instead of written by a model."""
    scope = dataset.analytics
    batch = dataset.batch_view

    if scope.boards_with_defects == 0:
        overview = translate(language, "fallback.overview_clean", boards_total=scope.boards_total)
    else:
        unknown = translate(language, "note.not_available")
        overview = translate(
            language,
            "fallback.overview_boards",
            boards_with_defects=scope.boards_with_defects,
            boards_total=scope.boards_total,
            defect_rate=format_percent(scope.defect_rate, language),
            defect_total=scope.defect_total,
            classes=len(scope.by_defect_class),
            severity=label_enum(language, scope.severity, fallback=unknown),
        )

    notes: dict[DefectType, str] = {}
    for stat in batch.by_defect_class:
        key = "fallback.note_recurring" if stat.is_recurring else "fallback.note_isolated"
        notes[stat.defect_type] = translate(
            language,
            key,
            defect=label_enum(language, stat.defect_type).capitalize(),
            occurrences=stat.occurrences,
            boards=stat.boards_affected,
            boards_total=stat.boards_total,
            share=format_percent(stat.share_of_boards, language),
        )

    recommendations = [
        translate(
            language,
            "fallback.recommendation_review",
            defect=label_enum(language, stat.defect_type),
        )
        for stat in batch.by_defect_class[:3]
    ]
    if scope.boards_without_disposition:
        recommendations.append(
            translate(
                language,
                "fallback.recommendation_disposition",
                count=scope.boards_without_disposition,
            )
        )
    if scope.analyses_pending_review:
        recommendations.append(
            translate(
                language, "fallback.recommendation_validate", count=scope.analyses_pending_review
            )
        )

    return ReportNarrative(
        overview=overview,
        defect_notes=notes,
        recommendations=recommendations[:_MAX_RECOMMENDATIONS],
        written_by_model=False,
    )


def _from_model_output(
    raw: _NarrativeOutput, known_classes: list[DefectClassStat]
) -> ReportNarrative:
    by_value = {stat.defect_type.value: stat.defect_type for stat in known_classes}
    notes: dict[DefectType, str] = {}
    for entry in raw.defect_notes:
        defect_type = by_value.get(entry.defect_type.strip().lower())
        if defect_type is not None and entry.note.strip():
            notes[defect_type] = strip_dashes(entry.note.strip())
    return ReportNarrative(
        overview=strip_dashes(raw.overview.strip()),
        defect_notes=notes,
        recommendations=[
            strip_dashes(item.strip()) for item in raw.recommendations if item and item.strip()
        ][:_MAX_RECOMMENDATIONS],
        written_by_model=True,
    )


async def build_narrative(
    db: AsyncSession,
    dataset: ReportDataset,
    *,
    language: ReportLanguage,
    client: LLMClient | None = None,
) -> ReportNarrative:
    """Never raises: any failure to reach or parse the model degrades to `_computed_narrative`
    with a warning, exactly like the analysis chain degrading to the baseline.
    """
    if dataset.analytics.boards_total == 0:
        return _computed_narrative(dataset, language)

    llm = client or await build_llm_client(db, role="report")
    if llm is None:
        return _computed_narrative(dataset, language)

    classes = dataset.batch_view.by_defect_class
    try:
        payload = await llm.complete_json(
            system=_system_prompt(language, [stat.defect_type.value for stat in classes]),
            user=_facts(dataset, language=language),
        )
        parsed = _NarrativeOutput.model_validate(payload)
    except (LLMUnavailableError, ValidationError, ValueError) as exc:
        logger.warning("Report narrative: falling back to computed text (%s)", exc)
        return _computed_narrative(dataset, language)

    narrative = _from_model_output(parsed, classes)
    if not narrative.overview:
        return _computed_narrative(dataset, language)

    # A model that skipped a class still leaves the report with a note for it, taken from the
    # computed text, so the frequency section never has holes in it.
    computed = _computed_narrative(dataset, language)
    merged = {**computed.defect_notes, **narrative.defect_notes}
    return ReportNarrative(
        overview=narrative.overview,
        defect_notes=merged,
        recommendations=narrative.recommendations or computed.recommendations,
        written_by_model=True,
    )
