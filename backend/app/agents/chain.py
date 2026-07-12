"""Analyst -> Reviewer -> Summarizer orchestration (PRD 5.3, issue #31).

Plain, testable async orchestration rather than a LangGraph state graph (PRD section 5.1) —
three sequential structured-output calls plus a bounded reject/revise loop don't need a
state-graph runtime to stay deterministic; `max_review_attempts` bounds the chain's only loop
so a misbehaving model can't hang the task (issue #31's "Reviewer Loop Bounded" acceptance
criterion).

`run_chain` raises `AgentChainAbortedError` for every failure mode that should degrade
gracefully to the baseline analysis. Callers (`app.tasks.pipeline`) catch exactly that type and
never let it fail the Celery task — see the module docstring on `app.agents.errors`.
"""

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.agents.analyst import run_analyst
from app.agents.errors import AgentChainAbortedError
from app.agents.llm_client import LLMClient
from app.agents.prompts.v1 import PROMPT_VERSION
from app.agents.reviewer import run_reviewer
from app.agents.schemas import AnalystFinding
from app.agents.summarizer import run_summarizer
from app.models import Detection
from app.models.enums import DispositionRecommendation, Severity, severity_rank

logger = logging.getLogger(__name__)

DEFAULT_MAX_REVIEW_ATTEMPTS = 2


@dataclass(frozen=True)
class AgentChainResult:
    per_defect: list[dict[str, Any]]
    executive_summary: str
    disposition_recommendation: DispositionRecommendation
    severity_max: Severity
    llm_provider: str
    llm_model: str
    prompt_version: str
    tokens_used: int | None
    duration_ms: int


def _finding_to_dict(finding: AnalystFinding) -> dict[str, Any]:
    """Matches the persisted `Analysis.per_defect` shape (section 11.5) — `functional_impact`
    is part of the Analyst/Reviewer's working output (PRD 5.3) but isn't part of the
    documented, tested `per_defect` contract baseline analyses already populate (issue #7), so
    it stays out of the persisted dict here too rather than silently widening that shape.
    """
    return {
        "detection_id": finding.detection_id,
        "description": finding.description,
        "probable_causes": finding.probable_causes,
        "suggested_solutions": finding.suggested_solutions,
        "severity": finding.severity.value,
    }


def _validate_coverage(findings: Sequence[AnalystFinding], detections: Sequence[Detection]) -> None:
    expected = {str(d.id) for d in detections}
    actual = {f.detection_id for f in findings}
    if actual != expected:
        raise AgentChainAbortedError(
            f"Analyst/Reviewer output detection_id mismatch: expected {sorted(expected)}, "
            f"got {sorted(actual)}"
        )


async def _draft_until_approved(
    client: LLMClient,
    *,
    board_number: str | None,
    batch_number: str | None,
    detections: Sequence[Detection],
    max_review_attempts: int,
) -> list[AnalystFinding]:
    corrections: list[str] | None = None
    for attempt in range(1, max_review_attempts + 1):
        draft = await run_analyst(
            client,
            board_number=board_number,
            batch_number=batch_number,
            detections=detections,
            corrections=corrections,
        )
        _validate_coverage(draft.findings, detections)

        review = await run_reviewer(client, detections=detections, draft_findings=draft.findings)

        if review.approved:
            findings = review.revised_findings or draft.findings
            _validate_coverage(findings, detections)
            return findings

        if attempt >= max_review_attempts:
            logger.warning(
                "Agent chain: Reviewer rejected %d attempt(s), giving up: %s",
                attempt,
                review.corrections,
            )
            raise AgentChainAbortedError(
                f"Reviewer rejected {attempt} attempt(s) without approval: "
                f"{'; '.join(review.corrections) or 'no reason given'}"
            )

        logger.info(
            "Agent chain: Reviewer rejected attempt %d, requesting revision: %s",
            attempt,
            review.corrections,
        )
        corrections = review.corrections

    raise AgentChainAbortedError("unreachable: loop must return or raise")  # pragma: no cover


async def run_chain(
    client: LLMClient,
    *,
    board_number: str | None,
    batch_number: str | None,
    detections: Sequence[Detection],
    max_review_attempts: int = DEFAULT_MAX_REVIEW_ATTEMPTS,
) -> AgentChainResult:
    """Runs the full chain for one image's reportable detections.

    `max_review_attempts` bounds how many Analyst drafts get reviewed before giving up (must
    be >= 1) — `app.tasks.pipeline` passes the `agent_analysis_max_review_attempts` config
    value (issue #31) through here rather than hardcoding it.
    """
    if not detections:
        raise AgentChainAbortedError("run_chain called with no detections")
    if max_review_attempts < 1:
        raise AgentChainAbortedError("max_review_attempts must be >= 1")

    started = time.monotonic()

    final_findings = await _draft_until_approved(
        client,
        board_number=board_number,
        batch_number=batch_number,
        detections=detections,
        max_review_attempts=max_review_attempts,
    )
    summary = await run_summarizer(
        client, board_number=board_number, batch_number=batch_number, findings=final_findings
    )

    return AgentChainResult(
        per_defect=[_finding_to_dict(f) for f in final_findings],
        executive_summary=summary.executive_summary,
        disposition_recommendation=summary.disposition_recommendation,
        severity_max=max(final_findings, key=lambda f: severity_rank(f.severity)).severity,
        llm_provider=getattr(client, "provider", "unknown"),
        llm_model=getattr(client, "model", "unknown"),
        prompt_version=PROMPT_VERSION,
        tokens_used=getattr(client, "total_tokens_used", None),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
