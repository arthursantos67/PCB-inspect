"""The Summarizer (PRD 5.3): consolidates the reviewed per-defect findings into the board's
executive summary and disposition recommendation.
"""

from collections.abc import Sequence

from pydantic import ValidationError

from app.agents.errors import AgentChainAbortedError
from app.agents.llm_client import LLMClient, LLMUnavailableError
from app.agents.prompts import v1 as prompts
from app.agents.schemas import AnalystFinding, SummarizerOutput


async def run_summarizer(
    client: LLMClient,
    *,
    board_number: str | None,
    batch_number: str | None,
    findings: Sequence[AnalystFinding],
) -> SummarizerOutput:
    system = prompts.summarizer_system_prompt()
    user = prompts.summarizer_user_prompt(
        board_number=board_number, batch_number=batch_number, findings=findings
    )
    try:
        raw = await client.complete_json(system=system, user=user)
        return SummarizerOutput.model_validate(raw)
    except LLMUnavailableError as exc:
        raise AgentChainAbortedError(f"Summarizer call failed: {exc}") from exc
    except ValidationError as exc:
        raise AgentChainAbortedError(f"Summarizer returned malformed output: {exc}") from exc
