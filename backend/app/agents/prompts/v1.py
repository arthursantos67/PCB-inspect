"""Prompt templates for the Analyst/Reviewer/Summarizer chain, version "v1" (RA-03: prompts
are versioned in the repository, not the database — `PROMPT_VERSION` is persisted on every
agent-sourced `Analysis` row so a later prompt revision doesn't retroactively relabel old
output).

Detections are described textually (class, confidence, and a plain-language board position
computed from the normalized bbox by `position_phrase`) rather than passing
image bytes — the six defect classes are fixed and well documented (`app.knowledge.defects`),
and grounding the Analyst/Reviewer in that curated knowledge base plus the real `Detection`
rows (the "tool-sourced facts" issue #31 calls out) is what keeps the chain from inventing a
cause incompatible with the defect type, without requiring a vision-capable model as a hard
dependency of the local-first default (section 5.2).
"""

from collections.abc import Sequence

from app.agents.batch_context import BatchContext
from app.agents.schemas import AnalystFinding
from app.core.language import Language
from app.knowledge.defects import DEFECT_KNOWLEDGE_BASE
from app.models import Detection

# Still "v1" after the language directive below (issue #50): the English prompts are
# behaviourally unchanged (they gained a line telling a model already writing English to write
# English), and which language an analysis came out in is recorded on the analysis row itself
# rather than smuggled into the prompt version, so RA-03's "don't retroactively relabel old
# output" still holds.
PROMPT_VERSION = "v1"

# The prompts themselves stay in English in every station language (issue #50). Only the text
# the operator reads switches: instructions, field names and the reference knowledge are what
# the model reasons *with*, and local models follow English instructions markedly better than
# translated ones. So the language directive names exactly which fields are operator-facing
# and leaves everything structural alone.
_WRITE_IN: dict[Language, str] = {
    Language.EN: (
        "Write every text you produce in English: description, probable_causes, "
        "suggested_solutions, functional_impact, executive_summary, and any correction you "
        "write for another agent."
    ),
    Language.PT: (
        "Write every text you produce in Brazilian Portuguese, using the vocabulary a PCB "
        "manufacturing engineer would use: description, probable_causes, suggested_solutions, "
        "functional_impact, executive_summary, and any correction you write for another agent. "
        "The JSON keys, the detection_id values, the defect class names and the enum values "
        "(low, medium, high, critical, approve, rework, discard) stay exactly as given, in "
        "English, and are never translated. Do not mix the two languages inside one sentence, "
        "and never answer in English because the instructions are in English."
    ),
}


def write_in(language: Language) -> str:
    return _WRITE_IN.get(language, _WRITE_IN[Language.EN])

_JSON_ONLY = (
    "Respond with a single JSON object only. No prose, no markdown code fences, no keys "
    "beyond the ones described."
)

# The operator reads this text verbatim on the analysis screen
# and does not want em dashes in it. Instructing the model is only half the fix (a local model
# ignores it often enough to matter), so `app.agents.chain` also strips them from the output.
_NO_EM_DASHES = (
    "Never use em dashes or en dashes in any text you write. Use a comma, a colon, or a "
    "separate sentence instead."
)

# Findings used to read as generic notes about a defect class, leaving the operator unable to
# tell which of five detections on the board a paragraph was about.
_BE_SPECIFIC = (
    "Every description must open by identifying the detection it is about: its defect class "
    "and where it sits on the board, taken from that detection's given position, plus the "
    "detector's confidence "
    "whenever it is low or moderate. Two detections of the same class on the same board must not "
    "receive interchangeable text: say what differs between them (position, size, confidence). "
    "Do not repeat the reference description back verbatim, and do not pad with generic "
    "statements that would be true of any board."
)

# The Analyst and the Reviewer each used to invent their own threshold for what counts as "low"
# confidence, so the Reviewer could reject a whole draft over the adjective alone: a detection at
# 0.81 was described as low, and the Reviewer rejected it for not being "moderate". Naming the
# bands numerically gives both agents the same scale, so confidence wording stops being arguable.
_CONFIDENCE_BANDS = (
    "Confidence bands: below 0.50 is low, 0.50 to 0.80 inclusive is moderate, above 0.80 is "
    "high. Use those words for those ranges and never redefine them."
)

# The same failure mode as the confidence bands, one level up: the Reviewer was told to reject a
# draft that never says which detection it is about, but never told how a draft is supposed to
# say it. Reading a ground truth keyed by detection_id, it concluded the UUID belonged in the
# prose and rejected drafts for leaving it out, which contradicts the Analyst's own instructions.
# Both agents now get the same definition of what identifying a detection means.
# The Reviewer used to be handed "<same shape as the Analyst's findings>", a spec it cannot
# resolve because it never sees the Analyst's system prompt. The only field names it did see were
# the ones `reviewer_user_prompt` renders, so it emitted those, and `ReviewerOutput` rejected
# every revision it wrote (six findings, three wrong keys each, 18 validation errors, whole chain
# degraded). Both agents now emit from this one spelled-out shape and the draft is rendered with
# these same names, so the two can no longer drift apart.
_FINDING_SHAPE = (
    '{"detection_id": str, "description": str, "probable_causes": [str], '
    '"suggested_solutions": [str], "severity": str, "functional_impact": str}'
)

_IDENTIFIES_BY = (
    "A description identifies its detection by naming the defect class and where it sits on the "
    "board in plain terms, never by quoting the detection_id. The id travels in its own field "
    "and must never appear in prose an operator reads."
)


def _board_context(board_number: str | None, batch_number: str | None) -> str:
    return f"Board {board_number or 'unknown'} from batch {batch_number or 'unknown'}."


# The nine zones a detection's centre can fall into, as language independent keys. Reports
# render them in the operator's language (`app.reports.strings.format_position`), the prompts
# below in English, so the wording lives with each consumer and the geometry only here.
POSITION_ZONE_EN: dict[str, str] = {
    "centre": "centre of the board",
    "upper_left": "upper left",
    "upper_centre": "upper centre",
    "upper_right": "upper right",
    "middle_left": "middle left",
    "middle_right": "middle right",
    "lower_left": "lower left",
    "lower_centre": "lower centre",
    "lower_right": "lower right",
}


def position_zone(bbox: dict[str, float]) -> str:
    """Which third of the board, vertically and horizontally, the detection's centre sits in."""
    centre_x = (bbox["x1"] + bbox["x2"]) / 2
    centre_y = (bbox["y1"] + bbox["y2"]) / 2
    horizontal = "left" if centre_x < 1 / 3 else "right" if centre_x > 2 / 3 else "centre"
    vertical = "upper" if centre_y < 1 / 3 else "lower" if centre_y > 2 / 3 else "middle"
    if horizontal == "centre" and vertical == "middle":
        return "centre"
    return f"{vertical}_{horizontal}"


def position_phrase(bbox: dict[str, float]) -> str:
    """Where a detection sits on the board, in words, computed here instead of by the model.

    The Reviewer rejects a draft whose same-class descriptions are interchangeable, and on a
    board carrying six `short` detections the only thing telling them apart is position. Handing
    the model a raw normalised bbox made deriving that its job, and a small local model reliably
    fails the arithmetic: it read six 14-decimal float pairs and wrote six interchangeable
    paragraphs, so every draft got rejected for a reason the Analyst had no practical way to fix.
    The percentages are kept alongside the zone because two detections often land in the same
    third of the board and still need to be told apart.
    """
    centre_x = (bbox["x1"] + bbox["x2"]) / 2
    centre_y = (bbox["y1"] + bbox["y2"]) / 2
    return (
        f"{POSITION_ZONE_EN[position_zone(bbox)]}, centred at x={centre_x * 100:.0f}% "
        f"y={centre_y * 100:.0f}% of the board, "
        f"box {(bbox['x2'] - bbox['x1']) * 100:.1f}% wide and "
        f"{(bbox['y2'] - bbox['y1']) * 100:.1f}% tall"
    )


def _detection_lines(
    detections: Sequence[Detection], batch_context: BatchContext | None = None
) -> str:
    lines = []
    for detection in detections:
        entry = DEFECT_KNOWLEDGE_BASE[detection.defect_type]
        line = (
            f"- detection_id={detection.id} class={detection.defect_type.value} "
            f"confidence={float(detection.confidence):.2f} "
            f"position={position_phrase(detection.bbox)} "
            f"| reference_severity={entry.severity.value} "
            f"reference_description={entry.description}"
        )
        if batch_context is not None:
            frequency = batch_context.frequency(detection.defect_type)
            line += (
                f" | batch_occurrences={frequency.occurrences} "
                f"batch_boards_affected={frequency.boards_affected}"
            )
        lines.append(line)
    return "\n".join(lines)


def _batch_frequency_block(batch_context: BatchContext | None) -> str | None:
    """The batch's defect footprint so far, so the Analyst can weigh an isolated occurrence
    differently from a recurring one.
    """
    if batch_context is None:
        return None
    lines = [
        f"Batch {batch_context.batch_number} inspected so far: "
        f"{batch_context.boards_inspected} board(s), of which "
        f"{batch_context.boards_with_defects} have at least one reported defect.",
        "Per defect class already seen in this batch (this board included):",
    ]
    if batch_context.frequencies:
        lines += [
            f"- {defect_type.value}: {frequency.occurrences} occurrence(s) across "
            f"{frequency.boards_affected} board(s)"
            for defect_type, frequency in sorted(
                batch_context.frequencies.items(), key=lambda item: item[0].value
            )
        ]
    else:
        lines.append("- none")
    return "\n".join(lines)


def analyst_system_prompt(language: Language = Language.EN) -> str:
    return (
        write_in(language)
        + " "
        + "You are the Analyst in a PCB defect inspection pipeline. For each listed detection, "
        "write a technical interpretation: description, probable_causes, suggested_solutions, "
        "severity (low|medium|high|critical), and functional_impact. Ground every claim in the "
        "detection's class and the reference knowledge provided. Never invent a cause "
        "incompatible with the defect's class. "
        + _BE_SPECIFIC
        + " "
        + _IDENTIFIES_BY
        + " "
        + _CONFIDENCE_BANDS
        + " When batch frequency figures are given, use them: a class seen once in the batch "
        "is most likely an isolated occurrence, while one recurring on many boards of the same "
        "batch suggests a shared cause upstream (stencil, paste deposition, placement program, "
        "handling). Frequency is evidence, not proof, so state it as a possibility, keep the "
        "simpler local explanations on the table, and never claim a systemic cause the counts "
        "do not support. "
        + _NO_EM_DASHES
        + " "
        + _JSON_ONLY
        + ' Shape: {"findings": ['
        + _FINDING_SHAPE
        + ", ...]}, with exactly one entry per detection_id listed."
    )


def analyst_user_prompt(
    *,
    board_number: str | None,
    batch_number: str | None,
    detections: Sequence[Detection],
    corrections: Sequence[str] | None = None,
    batch_context: BatchContext | None = None,
) -> str:
    parts = [
        _board_context(board_number, batch_number),
        "Detections:",
        _detection_lines(detections, batch_context),
    ]
    frequency_block = _batch_frequency_block(batch_context)
    if frequency_block is not None:
        parts.append(frequency_block)
    if corrections:
        parts.append(
            "A reviewer rejected your previous draft for these reasons. Address every one "
            "of them in this revision:\n" + "\n".join(f"- {c}" for c in corrections)
        )
    return "\n\n".join(parts)


def reviewer_system_prompt(language: Language = Language.EN) -> str:
    return (
        write_in(language)
        + " The draft you are reviewing is written in that same language. Never reject a draft "
        "over the language it is written in, and never ask for it to be translated: judge only "
        "what it says. "
        + "You are the Reviewer in a PCB defect inspection pipeline. Check the Analyst's draft "
        "findings against the detections' actual classes and the reference knowledge — reject "
        "anything that names a cause or solution incompatible with the detection's class, uses "
        "vocabulary outside the six known defect types, or omits a detection_id that was "
        "listed. Also reject a draft whose descriptions are interchangeable between two "
        "detections of the same class, that never says which detection it is about, or that "
        "asserts a batch-wide systemic cause the given occurrence counts do not support. "
        + _IDENTIFIES_BY
        + " Never ask for the detection_id to be written into a description. "
        + _CONFIDENCE_BANDS
        + " Those are the only grounds for rejection. When the draft is factually sound but "
        "you would word something differently, approve it and put your wording into "
        "revised_findings rather than rejecting: a rejection throws the draft away and costs a "
        "full re-analysis, so never spend one on phrasing, style, or a synonym you prefer. If "
        "it has a real problem, reject it and explain exactly what to fix. Do not approve and "
        "reject in the same response. "
        + _NO_EM_DASHES
        + " "
        + _JSON_ONLY
        + ' Shape: {"approved": bool, "corrections": [str], "revised_findings": ['
        + _FINDING_SHAPE
        + ", ...] | null}. Whenever you fill revised_findings, every entry must carry all six "
        "keys spelled exactly as above, with one entry per detection_id listed. Copy the "
        "Analyst's values across unchanged for the parts you are not correcting."
    )


def reviewer_user_prompt(
    *,
    detections: Sequence[Detection],
    draft_findings: Sequence[AnalystFinding],
    batch_context: BatchContext | None = None,
) -> str:
    draft_lines = "\n".join(
        f"- detection_id={f.detection_id} severity={f.severity.value} "
        f"description={f.description} probable_causes={f.probable_causes} "
        f"suggested_solutions={f.suggested_solutions} "
        f"functional_impact={f.functional_impact}"
        for f in draft_findings
    )
    parts = [
        f"Ground-truth detections:\n{_detection_lines(detections, batch_context)}",
        f"Analyst's draft findings:\n{draft_lines}",
    ]
    frequency_block = _batch_frequency_block(batch_context)
    if frequency_block is not None:
        parts.insert(1, frequency_block)
    return "\n\n".join(parts)


def summarizer_system_prompt(language: Language = Language.EN) -> str:
    return (
        write_in(language)
        + " "
        + "You are the Summarizer in a PCB defect inspection pipeline. Consolidate the reviewed "
        "per-defect findings for this board into a plain-language executive summary, an "
        "overall disposition_recommendation (approve|rework|discard), and a priority "
        "(low|medium|high|critical) reflecting how urgently this board needs attention. "
        "The summary must be about this board specifically: say how many defects were found "
        "and of which classes, and where the worst one is. When batch figures are given, say "
        "in one sentence whether what this board shows looks isolated within its batch or "
        "part of a recurring pattern, and keep that as a possibility rather than a verdict. "
        "Do not restate each finding in full and do not write anything that would read the "
        "same for a different board. "
        + _NO_EM_DASHES
        + " "
        + _JSON_ONLY
        + ' Shape: {"executive_summary": str, "disposition_recommendation": str, '
        '"priority": str}.'
    )


def summarizer_user_prompt(
    *,
    board_number: str | None,
    batch_number: str | None,
    findings: Sequence[AnalystFinding],
    batch_context: BatchContext | None = None,
) -> str:
    finding_lines = "\n".join(
        f"- {f.detection_id}: {f.severity.value} severity: {f.description}" for f in findings
    )
    parts = [
        _board_context(board_number, batch_number),
        f"Reviewed findings:\n{finding_lines}",
    ]
    frequency_block = _batch_frequency_block(batch_context)
    if frequency_block is not None:
        parts.append(frequency_block)
    return "\n\n".join(parts)
