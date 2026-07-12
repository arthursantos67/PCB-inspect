"""The Reviewer (PRD 5.3): checks the Analyst's draft against the ground-truth `Detection`
rows and the knowledge-base reference facts, and either approves (optionally with in-place
corrections) or rejects with a reason that feeds the next Analyst attempt.
"""

from collections.abc import Sequence

from pydantic import ValidationError

from app.agents.errors import AgentChainAbortedError
from app.agents.llm_client import LLMClient, LLMUnavailableError
from app.agents.prompts import v1 as prompts
from app.agents.schemas import AnalystFinding, ReviewerOutput
from app.models import Detection


async def run_reviewer(
    client: LLMClient,
    *,
    detections: Sequence[Detection],
    draft_findings: Sequence[AnalystFinding],
) -> ReviewerOutput:
    system = prompts.reviewer_system_prompt()
    user = prompts.reviewer_user_prompt(detections=detections, draft_findings=draft_findings)
    try:
        raw = await client.complete_json(system=system, user=user)
        return ReviewerOutput.model_validate(raw)
    except LLMUnavailableError as exc:
        raise AgentChainAbortedError(f"Reviewer call failed: {exc}") from exc
    except ValidationError as exc:
        raise AgentChainAbortedError(f"Reviewer returned malformed output: {exc}") from exc
