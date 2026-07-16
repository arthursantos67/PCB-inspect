"""The chat agent's tool-calling loop (PRD 5.4, FR-09, issue #32).

Plain async orchestration, same rationale as `app.agents.chain` (PRD section 5.1): a
bounded tool-call/respond loop doesn't need a state-graph runtime to stay deterministic and
testable with a scripted stub LLM client.

Streaming design: the configured LLM's OpenAI-compatible endpoint is called with
`stream=False` (`ChatLLMClient.complete_chat`) rather than parsing that provider's raw SSE
chunk format — tool-calling arguments arrive fragmented across chunks in that format and
reassembling them adds real complexity for no behavioral difference an operator would notice,
since the *tool* round trips (the slow, network-bound part) already happen as their own
distinct SSE events below. Once the model's final answer is in hand, it is re-chunked into
several `content_delta` SSE events instead of one — satisfying issue #32's "renders
incrementally, not as one blocking request" criterion — rather than sent as a single event.

Tool-Only Facts (issue #32's acceptance criterion): production data enters the conversation
sent to the LLM through exactly one channel — a `tool` role message appended right after a
matching tool call, here or in `_context_preload_messages` below. The system prompt and every
`user`/`assistant` message are plain text with no server-injected data, so any factual claim
the model makes about production data is only ever backed by a tool result that is actually
in this conversation.
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_client import ChatLLMClient, LLMUnavailableError
from app.chat.errors import ChatAgentUnavailableError
from app.chat.prompts import SYSTEM_PROMPT
from app.chat.tools import TOOL_SCHEMAS, execute_tool, get_analysis
from app.models import Analysis, ChatMessage

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5
_CONTEXT_PRELOAD_TOOL_CALL_ID = "context-preload"
_CONTENT_CHUNK_SIZE = 40


async def _history_messages(db: AsyncSession, session_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
    ).scalars().all()
    return [{"role": row.role.value, "content": row.content} for row in rows]


async def _context_preload_messages(
    db: AsyncSession, context_analysis_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Synthesizes an assistant tool-call + tool-result pair for `get_analysis` on every turn
    of a context-scoped session (FE-03) — so the model always has that inspection's data
    without the operator re-typing which board they mean, while keeping the "production data
    only via a tool result" invariant intact (module docstring).

    `ChatSession.context_analysis_id` is a PRD-mandated FK to `Analysis` (PRD 10.2), but the
    `get_analysis` tool takes an inspection id (matching `GET /api/v1/inspections/{id}`'s
    detail shape, which is what the rest of the app already keys on) — so this first resolves
    the analysis to its 1:1 `image_id` before calling the tool.
    """
    analysis = await db.get(Analysis, context_analysis_id)
    inspection_id = analysis.image_id if analysis is not None else context_analysis_id
    arguments = {"inspection_id": str(inspection_id)}
    result = await get_analysis(db, arguments)
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": _CONTEXT_PRELOAD_TOOL_CALL_ID,
                    "type": "function",
                    "function": {"name": "get_analysis", "arguments": json.dumps(arguments)},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": _CONTEXT_PRELOAD_TOOL_CALL_ID,
            "content": json.dumps(result, default=str),
        },
    ]


async def build_messages(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    context_analysis_id: uuid.UUID | None,
    user_content: str,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context_analysis_id is not None:
        messages += await _context_preload_messages(db, context_analysis_id)
    messages += await _history_messages(db, session_id)
    messages.append({"role": "user", "content": user_content})
    return messages


async def run_turn(
    db: AsyncSession,
    llm_client: ChatLLMClient,
    *,
    session_id: uuid.UUID,
    context_analysis_id: uuid.UUID | None,
    user_content: str,
) -> AsyncIterator[dict[str, Any]]:
    """Yields SSE-ready event dicts: `tool_call` while a tool is running, `content_delta` for
    each chunk of the final answer, then exactly one terminal `done` carrying the full
    persistable content and the recorded tool calls. Raises `ChatAgentUnavailableError` (never
    yields an event for this) on any LLM failure or an exhausted tool-call bound — the router
    is what turns that into the single `error` SSE event UC-7 calls for.
    """
    messages = await build_messages(
        db,
        session_id=session_id,
        context_analysis_id=context_analysis_id,
        user_content=user_content,
    )
    recorded_tool_calls: list[dict[str, Any]] = []

    for _iteration in range(MAX_TOOL_ITERATIONS):
        try:
            completion = await llm_client.complete_chat(messages=messages, tools=TOOL_SCHEMAS)
        except LLMUnavailableError as exc:
            raise ChatAgentUnavailableError(str(exc)) from exc

        if not completion.tool_calls:
            content = completion.content or ""
            for start in range(0, len(content), _CONTENT_CHUNK_SIZE):
                chunk = content[start : start + _CONTENT_CHUNK_SIZE]
                yield {"type": "content_delta", "text": chunk}
            yield {"type": "done", "content": content, "tool_calls": recorded_tool_calls}
            return

        messages.append(
            {
                "role": "assistant",
                "content": completion.content,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                    }
                    for call in completion.tool_calls
                ],
            }
        )
        for call in completion.tool_calls:
            yield {"type": "tool_call", "name": call.name, "arguments": call.arguments}
            result = await execute_tool(db, call.name, call.arguments)
            recorded_tool_calls.append(
                {"id": call.id, "name": call.name, "arguments": call.arguments, "result": result}
            )
            tool_content = json.dumps(result, default=str)
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": tool_content}
            )

    raise ChatAgentUnavailableError(
        f"exceeded {MAX_TOOL_ITERATIONS} tool-calling iterations without a final answer"
    )
