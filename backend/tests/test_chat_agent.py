"""Chat agent tool-calling loop (PRD 5.4, issue #32). A stub LLM client drives every response
deterministically, mirroring tests/test_agents_chain.py's convention for the analysis chain.
"""

import json
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_client import ChatCompletion, LLMUnavailableError, ToolCallRequest
from app.chat.agent import MAX_TOOL_ITERATIONS, build_messages, run_turn
from app.chat.errors import ChatAgentUnavailableError
from app.models import (
    Analysis,
    Batch,
    Board,
    ChatSession,
    Detection,
    InspectionImage,
    ModelVersion,
    User,
)
from app.models.enums import (
    AnalysisSource,
    AnalysisStatus,
    DefectType,
    ImageSource,
    ImageStatus,
    Severity,
)


class _StubChatLLMClient:
    """Returns a scripted sequence of `ChatCompletion`s, one per call, in order — raises if
    called more times than scripted (an exact call-count assertion, same convention as
    tests/test_agents_chain.py's `_StubLLMClient`).
    """

    def __init__(self, responses: list[ChatCompletion]) -> None:
        self._responses = list(responses)
        self.calls: list[list[dict[str, Any]]] = []

    async def complete_chat(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ChatCompletion:
        # A shallow copy snapshots which messages existed *at this call* — `run_turn` keeps
        # appending to the same list object across iterations, so storing `messages` itself
        # would let a later call's appends leak backwards into an earlier call's recorded view.
        self.calls.append(list(messages))
        if not self._responses:
            raise AssertionError("stub LLM client called more times than scripted")
        return self._responses.pop(0)


async def _make_batch_with_defect(db: AsyncSession, batch_number: str, defect_count: int) -> None:
    model_version = ModelVersion(
        version=f"v-{uuid.uuid4().hex[:8]}", weights_path="/weights/best.pt", is_active=False
    )
    db.add(model_version)
    await db.flush()
    batch = Batch(batch_number=batch_number)
    db.add(batch)
    await db.flush()
    board = Board(batch_id=batch.id, board_number="B1")
    db.add(board)
    await db.flush()
    image = InspectionImage(
        board_id=board.id,
        source=ImageSource.WATCH_FOLDER,
        original_path=f"/tmp/{uuid.uuid4()}.jpg",
        checksum_sha256=uuid.uuid4().hex,
        status=ImageStatus.COMPLETED,
    )
    db.add(image)
    await db.flush()
    for _ in range(defect_count):
        db.add(
            Detection(
                image_id=image.id,
                defect_type=DefectType.SHORT,
                bbox={"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4},
                confidence=Decimal("0.900"),
                is_reported=True,
                model_version_id=model_version.id,
            )
        )
    await db.commit()


async def _make_user(db: AsyncSession) -> User:
    user = User(
        email=f"{uuid.uuid4().hex[:8]}@pcb-inspect.local",
        password_hash="hash",
        full_name="Operator",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_session(
    db: AsyncSession, *, context_analysis_id: uuid.UUID | None = None
) -> ChatSession:
    user = await _make_user(db)
    session = ChatSession(user_id=user.id, context_analysis_id=context_analysis_id)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def test_tool_only_facts_the_llm_never_sees_production_data_before_calling_a_tool(
    db_session: AsyncSession,
) -> None:
    """Issue #32's "Tool-Only Facts" acceptance criterion: the batch's real defect count
    (17) must never appear anywhere in the messages sent to the LLM before it calls a tool —
    the *only* way that number can end up in the model's context is the tool result message
    appended after the call. If the assistant's final answer states that number, it can only
    be because the tool ran and returned it, not because the model already knew it.
    """
    await _make_batch_with_defect(db_session, "BATCH-XYZ", defect_count=17)
    session = await _make_session(db_session)

    tool_call = ToolCallRequest(
        id="call-1", name="get_defect_stats", arguments={"group_by": "batch"}
    )
    client = _StubChatLLMClient(
        [
            ChatCompletion(content=None, tool_calls=[tool_call]),
            ChatCompletion(content="BATCH-XYZ had 17 defects.", tool_calls=[]),
        ]
    )

    events = [
        event
        async for event in run_turn(
            db_session,
            client,
            session_id=session.id,
            context_analysis_id=None,
            user_content="Which batch had the most defects?",
        )
    ]

    # The critical assertion: nothing in the first call's messages (system prompt, history,
    # the new user question) contains the real count — it was never available to fabricate.
    first_call_messages = client.calls[0]
    assert all("17" not in json.dumps(m) for m in first_call_messages)

    # The tool call actually happened and returned the real data...
    tool_call_events = [e for e in events if e["type"] == "tool_call"]
    assert tool_call_events == [
        {"type": "tool_call", "name": "get_defect_stats", "arguments": {"group_by": "batch"}}
    ]

    # ...and the second call to the LLM is the only place "17" could have come from.
    second_call_messages = client.calls[1]
    assert any("17" in json.dumps(m) for m in second_call_messages)

    done = next(e for e in events if e["type"] == "done")
    assert done["content"] == "BATCH-XYZ had 17 defects."
    assert done["tool_calls"][0]["name"] == "get_defect_stats"
    assert done["tool_calls"][0]["result"]["results"][0] == {
        "batch_number": "BATCH-XYZ",
        "defect_count": 17,
    }


async def test_run_turn_without_any_tool_call_still_streams_and_completes(
    db_session: AsyncSession,
) -> None:
    session = await _make_session(db_session)
    client = _StubChatLLMClient([ChatCompletion(content="Hello! How can I help?", tool_calls=[])])

    events = [
        event
        async for event in run_turn(
            db_session, client, session_id=session.id, context_analysis_id=None, user_content="hi"
        )
    ]

    assert len(client.calls) == 1
    content_deltas = "".join(e["text"] for e in events if e["type"] == "content_delta")
    assert content_deltas == "Hello! How can I help?"
    done = next(e for e in events if e["type"] == "done")
    assert done["tool_calls"] == []


async def test_run_turn_bounds_the_tool_calling_loop(db_session: AsyncSession) -> None:
    """A misbehaving model that keeps calling tools forever must not hang the request."""
    session = await _make_session(db_session)
    endless_tool_call = ToolCallRequest(
        id="call", name="get_defect_knowledge", arguments={"defect_type": "spur"}
    )
    client = _StubChatLLMClient(
        [
            ChatCompletion(content=None, tool_calls=[endless_tool_call])
            for _ in range(MAX_TOOL_ITERATIONS)
        ]
    )

    with pytest.raises(ChatAgentUnavailableError):
        async for _ in run_turn(
            db_session, client, session_id=session.id, context_analysis_id=None, user_content="hi"
        ):
            pass

    assert len(client.calls) == MAX_TOOL_ITERATIONS


async def test_run_turn_raises_when_llm_is_unreachable(db_session: AsyncSession) -> None:
    session = await _make_session(db_session)

    class _RaisingClient:
        async def complete_chat(self, **kwargs: Any) -> ChatCompletion:
            raise LLMUnavailableError("connection refused")

    with pytest.raises(ChatAgentUnavailableError, match="connection refused"):
        async for _ in run_turn(
            db_session,
            _RaisingClient(),
            session_id=session.id,
            context_analysis_id=None,
            user_content="hi",
        ):
            pass


async def test_context_scoped_session_preloads_the_analysis_via_a_synthetic_tool_call(
    db_session: AsyncSession,
) -> None:
    """FE-03's "Ask about this analysis" entry point: the operator never re-types which board
    they mean — but per the Tool-Only Facts invariant, that context must still enter the
    conversation as a tool result, not a bare injected string.
    """
    model_version = ModelVersion(version=f"v-{uuid.uuid4().hex[:8]}", weights_path="/x.pt")
    db_session.add(model_version)
    await db_session.flush()
    batch = Batch(batch_number="BATCH-CTX")
    db_session.add(batch)
    await db_session.flush()
    board = Board(batch_id=batch.id, board_number="B1")
    db_session.add(board)
    await db_session.flush()
    image = InspectionImage(
        board_id=board.id,
        source=ImageSource.WATCH_FOLDER,
        original_path="/tmp/x.jpg",
        checksum_sha256=uuid.uuid4().hex,
        status=ImageStatus.COMPLETED,
    )
    db_session.add(image)
    await db_session.flush()
    analysis = Analysis(
        image_id=image.id,
        status=AnalysisStatus.COMPLETED,
        source=AnalysisSource.KNOWLEDGE_BASE,
        severity_max=Severity.HIGH,
        executive_summary="unique-marker-summary",
    )
    db_session.add(analysis)
    await db_session.commit()

    messages = await build_messages(
        db_session,
        session_id=uuid.uuid4(),
        context_analysis_id=analysis.id,
        user_content="What's the severity here?",
    )

    # A tool-call/tool-result pair for get_analysis, injected before the user's question.
    assert messages[1]["role"] == "assistant"
    assert messages[1]["tool_calls"][0]["function"]["name"] == "get_analysis"
    assert messages[2]["role"] == "tool"
    assert "unique-marker-summary" in messages[2]["content"]
    assert messages[-1] == {"role": "user", "content": "What's the severity here?"}
