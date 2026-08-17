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
sent to the LLM through exactly one code path — `app.chat.tools.execute_tool`, reading the
database. Either the model asked for it (a `tool` role message right after its own call) or the
application preloaded the analysis the operator opened the chat from
(`_preloaded_context_message`). The system prompt and the transcript itself carry no
server-injected data, so any factual claim the model makes about production data is only ever
backed by a tool result that is actually in this conversation.
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_client import (
    ChatCompletion,
    ChatLLMClient,
    LLMUnavailableError,
    ToolCallRequest,
)
from app.chat.errors import ChatAgentUnavailableError
from app.chat.prompts import system_prompt
from app.chat.tools import TOOL_SCHEMAS, execute_tool, get_analysis
from app.models import Analysis, ChatMessage
from app.settings import service as settings_service

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5
_CONTENT_CHUNK_SIZE = 40

# Context budget. Everything the model sees has to be re-processed on every single turn, and
# on a local CPU model prompt processing *is* the latency — so old turns are dropped from
# what gets sent rather than accumulating forever. Nothing is deleted: the full transcript
# stays in the database and on screen, this only bounds the window handed to the model.
MAX_HISTORY_MESSAGES = 12
# Attached analyses are re-sent in full on every turn, so a hard cap keeps a session
# with many attachments from crowding out the conversation itself.
MAX_ATTACHMENTS = 5


async def _history_messages(db: AsyncSession, session_id: uuid.UUID) -> list[dict[str, Any]]:
    """The most recent `MAX_HISTORY_MESSAGES` turns, oldest first. Fetched newest-first and
    reversed so the trim drops the *oldest* messages, which is the useful half to discard.

    The turn's own question is already the last row here: the router persists it before running
    the turn (UC-7 keeps the question when the LLM fails), so this is the whole conversation the
    model sees, current question included.
    """
    rows = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(MAX_HISTORY_MESSAGES)
        )
    ).scalars().all()
    return [{"role": row.role.value, "content": row.content} for row in reversed(rows)]


def _assistant_tool_call(call: ToolCallRequest) -> dict[str, Any]:
    """One tool call rendered back into the assistant message that precedes its result.

    `extra_content` is carried through untouched when the provider sent one: Gemini 3.x
    rejects the follow-up request outright if the `thought_signature` it attached to the call
    does not come back with it (`app.agents.llm_client.ToolCallRequest`).
    """
    rendered: dict[str, Any] = {
        "id": call.id,
        "type": "function",
        "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
    }
    if call.extra_content:
        rendered["extra_content"] = call.extra_content
    return rendered


def _preloaded_context_message(
    tool_name: str, arguments: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    """One preloaded analysis, as a message the model reads before the operator's question.

    Deliberately *not* a synthesized assistant tool-call plus `tool` result pair, which is what
    this used to be. A tool result only exists in the wire format as the answer to a call the
    model itself made, and providers enforce that: Gemini rejects a fabricated call for missing
    the `thought_signature` it never issued, and rejects an orphan result for naming no call at
    all. Either way every turn of a session opened from an analysis 400s before the model sees
    the question.

    The Tool-Only Facts invariant (module docstring) is about provenance, not about the wire
    role: what is embedded here is the verbatim output of `execute_tool`, generated by the same
    code path the model's own calls go through, labelled as application-supplied so the model
    never reports it as something the operator said.
    """
    return {
        "role": "user",
        "content": (
            f"[Application context, not written by the operator] Result of {tool_name}("
            f"{json.dumps(arguments)}), attached to this conversation:\n"
            f"{json.dumps(result, default=str)}"
        ),
    }


async def _context_preload_messages(
    db: AsyncSession,
    context_analysis_id: uuid.UUID | None,
    attached_inspection_ids: list[str] | None,
) -> list[dict[str, Any]]:
    """Runs `get_analysis` on every turn for the session's originating analysis (FE-03's "Ask
    about this analysis") and for every analysis the operator attached by hand, embedding each
    result as a preloaded context message — so the model always has those inspections' data
    without the operator re-typing which board they mean, while keeping the Tool-Only Facts
    invariant intact (module docstring).

    `ChatSession.context_analysis_id` is a PRD-mandated FK to `Analysis` (PRD 10.2), but the
    `get_analysis` tool takes an inspection id (matching `GET /api/v1/inspections/{id}`'s
    detail shape, which is what the rest of the app already keys on) — so this first resolves
    the analysis to its 1:1 `image_id` before calling the tool. Attachments are stored as
    inspection ids already and need no such resolution.
    """
    inspection_ids: list[str] = []
    if context_analysis_id is not None:
        analysis = await db.get(Analysis, context_analysis_id)
        inspection_ids.append(
            str(analysis.image_id if analysis is not None else context_analysis_id)
        )
    for inspection_id in attached_inspection_ids or []:
        if inspection_id not in inspection_ids:
            inspection_ids.append(inspection_id)

    messages: list[dict[str, Any]] = []
    for inspection_id in inspection_ids[:MAX_ATTACHMENTS]:
        arguments = {"inspection_id": inspection_id}
        result = await get_analysis(db, arguments)
        if "error" in result:
            # An attachment whose inspection was purged by retention (FR-17) is silently
            # skipped rather than feeding the model an error it might repeat as a finding.
            continue
        messages.append(_preloaded_context_message("get_analysis", arguments, result))
    return messages


async def build_messages(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    context_analysis_id: uuid.UUID | None,
    attached_inspection_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """The full prompt for one turn: system, the preloaded analyses, then the transcript.

    The operator's current question is *not* appended on top of the history: it is already the
    last message the history query returns, and appending it again would send every question to
    the model twice, which on a local CPU model is prompt-processing latency paid for nothing.
    """
    # The station language (issue #50) is read here rather than passed in: it is a station
    # setting, not a property of the request, and every caller already has this session.
    language = await settings_service.get_language(db)
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt(language)}]
    messages += await _context_preload_messages(
        db, context_analysis_id, attached_inspection_ids
    )
    messages += await _history_messages(db, session_id)
    return messages


async def _complete(
    llm_client: ChatLLMClient, messages: list[dict[str, Any]]
) -> AsyncIterator[dict[str, Any] | ChatCompletion]:
    """One assistant turn, yielding `content_delta` event dicts as text is generated and the
    assembled `ChatCompletion` last.

    Prefers the client's token-level `stream_chat` (`app.agents.llm_client`) so the operator
    starts reading the answer while the model is still writing it — the single biggest change
    to how long the chat *feels*. Clients without it (the scripted stub the tests use) fall
    back to a blocking call re-chunked afterwards, which
    keeps the event shape identical either way.
    """
    stream_chat = getattr(llm_client, "stream_chat", None)
    if stream_chat is not None:
        async for chunk in stream_chat(messages=messages, tools=TOOL_SCHEMAS):
            if chunk.completion is not None:
                yield chunk.completion
                return
            if chunk.text:
                yield {"type": "content_delta", "text": chunk.text}
        raise ChatAgentUnavailableError("LLM stream ended without a completion")

    completion = await llm_client.complete_chat(messages=messages, tools=TOOL_SCHEMAS)
    if not completion.tool_calls:
        content = completion.content or ""
        for start in range(0, len(content), _CONTENT_CHUNK_SIZE):
            yield {"type": "content_delta", "text": content[start : start + _CONTENT_CHUNK_SIZE]}
    yield completion


async def run_turn(
    db: AsyncSession,
    llm_client: ChatLLMClient,
    *,
    session_id: uuid.UUID,
    context_analysis_id: uuid.UUID | None,
    attached_inspection_ids: list[str] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yields SSE-ready event dicts: `tool_call` while a tool is running, `content_delta` for
    each chunk of the final answer, then exactly one terminal `done` carrying the full
    persistable content and the recorded tool calls. Raises `ChatAgentUnavailableError` (never
    yields an event for this) on any LLM failure or an exhausted tool-call bound — the router
    is what turns that into the single `error` SSE event UC-7 calls for.

    The caller must have persisted the operator's question already (`append_user_message`);
    this reads the turn's question from the transcript rather than taking it as an argument.
    """
    messages = await build_messages(
        db,
        session_id=session_id,
        context_analysis_id=context_analysis_id,
        attached_inspection_ids=attached_inspection_ids,
    )
    recorded_tool_calls: list[dict[str, Any]] = []

    for _iteration in range(MAX_TOOL_ITERATIONS):
        completion: ChatCompletion | None = None
        streamed_text: list[str] = []
        try:
            async for item in _complete(llm_client, messages):
                if isinstance(item, ChatCompletion):
                    completion = item
                else:
                    streamed_text.append(item["text"])
                    yield item
        except LLMUnavailableError as exc:
            raise ChatAgentUnavailableError(str(exc)) from exc

        if completion is None:  # pragma: no cover — `_complete` always ends with one
            raise ChatAgentUnavailableError("LLM turn produced no completion")

        if not completion.tool_calls:
            yield {
                "type": "done",
                "content": completion.content or "".join(streamed_text),
                "tool_calls": recorded_tool_calls,
            }
            return

        if streamed_text:
            # The model narrated its intent before calling a tool; that text was already sent
            # to the client, so tell it to clear what it has rendered rather than leaving the
            # narration stuck above the real answer.
            yield {"type": "content_reset"}

        messages.append(
            {
                "role": "assistant",
                "content": completion.content,
                "tool_calls": [_assistant_tool_call(call) for call in completion.tool_calls],
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
