"""Prompt templates for the Analyst/Reviewer/Summarizer chain, version "v1" (RA-03: prompts
are versioned in the repository, not the database — `PROMPT_VERSION` is persisted on every
agent-sourced `Analysis` row so a later prompt revision doesn't retroactively relabel old
output).

Detections are described textually (class, confidence, normalized bbox) rather than passing
image bytes — the six defect classes are fixed and well documented (`app.knowledge.defects`),
and grounding the Analyst/Reviewer in that curated knowledge base plus the real `Detection`
rows (the "tool-sourced facts" issue #31 calls out) is what keeps the chain from inventing a
cause incompatible with the defect type, without requiring a vision-capable model as a hard
dependency of the local-first default (section 5.2).
"""

from collections.abc import Sequence

from app.agents.schemas import AnalystFinding
from app.knowledge.defects import DEFECT_KNOWLEDGE_BASE
from app.models import Detection

PROMPT_VERSION = "v1"

_JSON_ONLY = (
    "Respond with a single JSON object only — no prose, no markdown code fences, no keys "
    "beyond the ones described."
)


def _board_context(board_number: str | None, batch_number: str | None) -> str:
    return f"Board {board_number or 'unknown'} from batch {batch_number or 'unknown'}."


def _detection_lines(detections: Sequence[Detection]) -> str:
    lines = []
    for detection in detections:
        entry = DEFECT_KNOWLEDGE_BASE[detection.defect_type]
        lines.append(
            f"- detection_id={detection.id} class={detection.defect_type.value} "
            f"confidence={float(detection.confidence):.2f} bbox={detection.bbox} "
            f"| reference_severity={entry.severity.value} "
            f"reference_description={entry.description}"
        )
    return "\n".join(lines)


def analyst_system_prompt() -> str:
    return (
        "You are the Analyst in a PCB defect inspection pipeline. For each listed detection, "
        "write a technical interpretation: description, probable_causes, suggested_solutions, "
        "severity (low|medium|high|critical), and functional_impact. Ground every claim in the "
        "detection's class and the reference knowledge provided — never invent a cause "
        "incompatible with the defect's class. "
        + _JSON_ONLY
        + ' Shape: {"findings": [{"detection_id": str, "description": str, '
        '"probable_causes": [str], "suggested_solutions": [str], "severity": str, '
        '"functional_impact": str}, ...]} — exactly one entry per detection_id listed.'
    )


def analyst_user_prompt(
    *,
    board_number: str | None,
    batch_number: str | None,
    detections: Sequence[Detection],
    corrections: Sequence[str] | None = None,
) -> str:
    parts = [
        _board_context(board_number, batch_number),
        "Detections:",
        _detection_lines(detections),
    ]
    if corrections:
        parts.append(
            "A reviewer rejected your previous draft for these reasons — address every one "
            "of them in this revision:\n" + "\n".join(f"- {c}" for c in corrections)
        )
    return "\n\n".join(parts)


def reviewer_system_prompt() -> str:
    return (
        "You are the Reviewer in a PCB defect inspection pipeline. Check the Analyst's draft "
        "findings against the detections' actual classes and the reference knowledge — reject "
        "anything that names a cause or solution incompatible with the detection's class, uses "
        "vocabulary outside the six known defect types, or omits a detection_id that was "
        "listed. If the draft is sound, approve it (optionally with minor in-place "
        "corrections). If it has a real problem, reject it and explain exactly what to fix — "
        "do not approve and reject in the same response. "
        + _JSON_ONLY
        + ' Shape: {"approved": bool, "corrections": [str], "revised_findings": '
        "[<same shape as the Analyst's findings>] | null}."
    )


def reviewer_user_prompt(
    *, detections: Sequence[Detection], draft_findings: Sequence[AnalystFinding]
) -> str:
    draft_lines = "\n".join(
        f"- detection_id={f.detection_id} severity={f.severity.value} "
        f"description={f.description} causes={f.probable_causes} "
        f"solutions={f.suggested_solutions}"
        for f in draft_findings
    )
    return (
        f"Ground-truth detections:\n{_detection_lines(detections)}\n\n"
        f"Analyst's draft findings:\n{draft_lines}"
    )


def summarizer_system_prompt() -> str:
    return (
        "You are the Summarizer in a PCB defect inspection pipeline. Consolidate the reviewed "
        "per-defect findings for this board into a plain-language executive summary, an "
        "overall disposition_recommendation (approve|rework|discard), and a priority "
        "(low|medium|high|critical) reflecting how urgently this board needs attention. "
        + _JSON_ONLY
        + ' Shape: {"executive_summary": str, "disposition_recommendation": str, '
        '"priority": str}.'
    )


def summarizer_user_prompt(
    *, board_number: str | None, batch_number: str | None, findings: Sequence[AnalystFinding]
) -> str:
    finding_lines = "\n".join(
        f"- {f.detection_id}: {f.severity.value} severity — {f.description}" for f in findings
    )
    return f"{_board_context(board_number, batch_number)}\n\nReviewed findings:\n{finding_lines}"
