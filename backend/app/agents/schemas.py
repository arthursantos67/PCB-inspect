"""Structured I/O contracts for the Analyst/Reviewer/Summarizer chain (PRD section 5.3,
issue #31). Every agent call is validated against one of these on the way back from the LLM —
a malformed response is a `pydantic.ValidationError`, which `app.agents.chain` normalizes into
`AgentChainAbortedError` (graceful degrade to the baseline), never a raw crash.
"""

from pydantic import BaseModel, Field

from app.models.enums import DispositionRecommendation, Severity


class AnalystFinding(BaseModel):
    """One detection's technical interpretation (PRD 5.3's Analyst output)."""

    detection_id: str
    description: str
    probable_causes: list[str] = Field(min_length=1)
    suggested_solutions: list[str] = Field(min_length=1)
    severity: Severity
    functional_impact: str


class AnalystOutput(BaseModel):
    findings: list[AnalystFinding] = Field(min_length=1)


class ReviewerOutput(BaseModel):
    """PRD 5.3's Reviewer output. `revised_findings` is only meaningful when `approved` is
    `True` and the Reviewer chose to correct the draft in place rather than reject it outright
    (e.g. fixing a defect-type vocabulary slip without burning a whole reject/revise cycle);
    `corrections` explains *why* on a rejection and is what gets fed back into the next
    Analyst attempt (`app.agents.chain`).
    """

    approved: bool
    corrections: list[str] = Field(default_factory=list)
    revised_findings: list[AnalystFinding] | None = None


class SummarizerOutput(BaseModel):
    """PRD 5.3's Summarizer output, consolidating the reviewed per-defect findings."""

    executive_summary: str
    disposition_recommendation: DispositionRecommendation
    priority: Severity
