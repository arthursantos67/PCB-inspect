"""Chat session/message persistence and ownership checks (FR-09, PRD section 13: "the only
per-resource check is ownership for private data like chat sessions").
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.models import Analysis, ChatMessage, ChatSession
from app.models.enums import ChatRole

_TITLE_MAX_LENGTH = 80


def _derive_title(first_message: str) -> str:
    stripped = first_message.strip()
    if len(stripped) <= _TITLE_MAX_LENGTH:
        return stripped
    return stripped[: _TITLE_MAX_LENGTH - 1].rstrip() + "…"


async def create_session(
    db: AsyncSession, *, user_id: uuid.UUID, context_analysis_id: uuid.UUID | None
) -> ChatSession:
    if context_analysis_id is not None:
        analysis = await db.get(Analysis, context_analysis_id)
        if analysis is None:
            raise ApiError("RESOURCE_NOT_FOUND", "Analysis not found.", 404)

    session = ChatSession(user_id=user_id, context_analysis_id=context_analysis_id)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def list_sessions(db: AsyncSession, *, user_id: uuid.UUID) -> list[ChatSession]:
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.updated_at.desc())
    )
    return list(result.scalars().all())


async def _get_owned_session(
    db: AsyncSession, session_id: uuid.UUID, *, user_id: uuid.UUID
) -> ChatSession:
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise ApiError("RESOURCE_NOT_FOUND", "Chat session not found.", 404)
    if session.user_id != user_id:
        raise ApiError(
            "PERMISSION_DENIED", "This chat session belongs to another account.", 403
        )
    return session


async def get_session_with_messages(
    db: AsyncSession, session_id: uuid.UUID, *, user_id: uuid.UUID
) -> tuple[ChatSession, list[ChatMessage]]:
    session = await _get_owned_session(db, session_id, user_id=user_id)
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    return session, list(result.scalars().all())


async def get_owned_session(
    db: AsyncSession, session_id: uuid.UUID, *, user_id: uuid.UUID
) -> ChatSession:
    return await _get_owned_session(db, session_id, user_id=user_id)


async def delete_session(db: AsyncSession, session_id: uuid.UUID, *, user_id: uuid.UUID) -> None:
    session = await _get_owned_session(db, session_id, user_id=user_id)
    await db.delete(session)
    await db.commit()


async def append_user_message(db: AsyncSession, session: ChatSession, content: str) -> ChatMessage:
    """Persisted before the LLM is ever called, so the operator's question survives an LLM
    failure (UC-7's "LLM unavailable... session preserved" alternative flow).
    """
    if session.title is None:
        session.title = _derive_title(content)
    # Bumped explicitly — `onupdate=func.now()` only fires when the session ROW itself
    # changes, and turns after the first never touch `title` again, so listing "most recently
    # active first" (`list_sessions`) would otherwise go stale after each session's first turn.
    session.updated_at = datetime.now(UTC)
    message = ChatMessage(session_id=session.id, role=ChatRole.USER, content=content)
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


async def append_assistant_message(
    db: AsyncSession,
    session: ChatSession,
    *,
    content: str,
    tool_calls: list[dict[str, Any]] | None,
) -> ChatMessage:
    message = ChatMessage(
        session_id=session.id,
        role=ChatRole.ASSISTANT,
        content=content,
        tool_calls=tool_calls or None,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message
