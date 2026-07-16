"""`POST/GET /api/v1/chat/sessions`, `POST .../messages` (FR-09, PRD section 11.2) — chat
with tool-calling and SSE streaming (section 5.4). Ownership checked per PRD section 13: "the
only per-resource check is ownership for private data like chat sessions".
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_client import build_llm_client
from app.auth.dependencies import get_current_user
from app.chat import service
from app.chat.agent import run_turn
from app.chat.errors import ChatAgentUnavailableError
from app.chat.schemas import (
    ChatMessageCreate,
    ChatMessageOut,
    ChatSessionCreate,
    ChatSessionDetail,
    ChatSessionOut,
    PaginatedChatSessions,
)
from app.db.session import get_db
from app.models import ChatSession, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat/sessions", tags=["chat"])

# UC-7's "LLM unavailable" alternative flow: a temporary, plainly-worded note rather than a
# raw error — the operator's question is already safely persisted (`append_user_message` runs
# before the LLM is ever called), so nothing about their turn was lost.
_UNAVAILABLE_MESSAGE = (
    "The AI assistant is temporarily unavailable. Your question was saved — try again in a moment."
)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ChatSessionOut)
async def create_chat_session(
    payload: ChatSessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatSessionOut:
    session = await service.create_session(
        db, user_id=current_user.id, context_analysis_id=payload.context_analysis_id
    )
    return ChatSessionOut.model_validate(session)


@router.get("", response_model=PaginatedChatSessions)
async def list_chat_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedChatSessions:
    sessions = await service.list_sessions(db, user_id=current_user.id)
    return PaginatedChatSessions(results=[ChatSessionOut.model_validate(s) for s in sessions])


@router.get("/{session_id}", response_model=ChatSessionDetail)
async def get_chat_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatSessionDetail:
    session, messages = await service.get_session_with_messages(
        db, session_id, user_id=current_user.id
    )
    return ChatSessionDetail(
        id=session.id,
        title=session.title,
        context_analysis_id=session.context_analysis_id,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[ChatMessageOut.model_validate(m) for m in messages],
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    await service.delete_session(db, session_id, user_id=current_user.id)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def _message_stream(
    db: AsyncSession, session: ChatSession, content: str
) -> AsyncIterator[str]:
    await service.append_user_message(db, session, content)

    llm_client = await build_llm_client(db)
    if llm_client is None:
        message = await service.append_assistant_message(
            db, session, content=_UNAVAILABLE_MESSAGE, tool_calls=None
        )
        yield _sse("error", {"message": _UNAVAILABLE_MESSAGE})
        yield _sse("done", ChatMessageOut.model_validate(message).model_dump(mode="json"))
        return

    try:
        final_event: dict[str, Any] | None = None
        async for event in run_turn(
            db,
            llm_client,
            session_id=session.id,
            context_analysis_id=session.context_analysis_id,
            user_content=content,
        ):
            if event["type"] == "done":
                final_event = event
                continue
            yield _sse(event["type"], {k: v for k, v in event.items() if k != "type"})

        if final_event is None:  # pragma: no cover — run_turn always yields exactly one `done`
            raise ChatAgentUnavailableError("agent loop ended without a final answer")

        message = await service.append_assistant_message(
            db,
            session,
            content=final_event["content"],
            tool_calls=final_event["tool_calls"] or None,
        )
        yield _sse("done", ChatMessageOut.model_validate(message).model_dump(mode="json"))
    except ChatAgentUnavailableError:
        logger.warning("Chat turn failed for session %s", session.id, exc_info=True)
        message = await service.append_assistant_message(
            db, session, content=_UNAVAILABLE_MESSAGE, tool_calls=None
        )
        yield _sse("error", {"message": _UNAVAILABLE_MESSAGE})
        yield _sse("done", ChatMessageOut.model_validate(message).model_dump(mode="json"))


@router.post("/{session_id}/messages")
async def send_chat_message(
    session_id: uuid.UUID,
    payload: ChatMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    session = await service.get_owned_session(db, session_id, user_id=current_user.id)
    return StreamingResponse(
        _message_stream(db, session, payload.content),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
