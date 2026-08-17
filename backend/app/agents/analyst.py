"""The Analyst (PRD 5.3): drafts a technical finding per detection. Stateless — every call
gets the full detection set and, on a revision, the Reviewer's corrections from the previous
attempt (`app.agents.chain`'s reject/revise loop).
"""

from collections.abc import Sequence

from pydantic import ValidationError

from app.agents.batch_context import BatchContext
from app.agents.errors import AgentChainAbortedError
from app.agents.llm_client import LLMClient, LLMUnavailableError
from app.agents.prompts import v1 as prompts
from app.agents.schemas import AnalystOutput
from app.core.language import Language
from app.models import Detection


async def run_analyst(
    client: LLMClient,
    *,
    board_number: str | None,
    batch_number: str | None,
    detections: Sequence[Detection],
    corrections: Sequence[str] | None = None,
    batch_context: BatchContext | None = None,
    language: Language = Language.EN,
) -> AnalystOutput:
    system = prompts.analyst_system_prompt(language)
    user = prompts.analyst_user_prompt(
        board_number=board_number,
        batch_number=batch_number,
        detections=detections,
        corrections=corrections,
        batch_context=batch_context,
    )
    try:
        raw = await client.complete_json(system=system, user=user)
        return AnalystOutput.model_validate(raw)
    except LLMUnavailableError as exc:
        raise AgentChainAbortedError(f"Analyst call failed: {exc}") from exc
    except ValidationError as exc:
        raise AgentChainAbortedError(f"Analyst returned malformed output: {exc}") from exc
