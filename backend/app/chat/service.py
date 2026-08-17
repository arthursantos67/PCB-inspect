"""Chat session/message persistence and ownership checks (FR-09, PRD section 13: "the only
per-resource check is ownership for private data like chat sessions").
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.models import Analysis, Batch, Board, ChatMessage, ChatSession, InspectionImage
from app.models.enums import ChatRole

_TITLE_MAX_LENGTH = 80

# Mirrors `app.chat.agent.MAX_ATTACHMENTS`: attachments are re-sent in full on every turn, so
# the cap is enforced here too, where the operator gets a plain error instead of silently
# losing the attachment they just made.
MAX_ATTACHMENTS = 5


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


async def list_attachments(
    db: AsyncSession, session: ChatSession
) -> list[tuple[uuid.UUID, str | None, str | None]]:
    """The session's attached inspections as `(inspection_id, batch_number, board_number)`, in
    the order they were attached. Ids whose inspection no longer exists (retention purge,
    FR-17) are dropped from the result — the same silent skip `app.chat.agent` applies when it
    builds the context, so the chip list on screen matches what the model actually sees.
    """
    ids = [uuid.UUID(value) for value in session.attached_inspection_ids]
    if not ids:
        return []
    rows = (
        await db.execute(
            select(InspectionImage.id, Batch.batch_number, Board.board_number)
            .outerjoin(Board, InspectionImage.board_id == Board.id)
            .outerjoin(Batch, Board.batch_id == Batch.id)
            .where(InspectionImage.id.in_(ids))
        )
    ).all()
    by_id = {row[0]: (row[0], row[1], row[2]) for row in rows}
    return [by_id[image_id] for image_id in ids if image_id in by_id]


async def attach_inspection(
    db: AsyncSession, session: ChatSession, inspection_id: uuid.UUID
) -> ChatSession:
    image = await db.get(InspectionImage, inspection_id)
    if image is None:
        raise ApiError("RESOURCE_NOT_FOUND", "Inspection not found.", 404)

    attached = list(session.attached_inspection_ids)
    if str(inspection_id) in attached:
        return session
    if len(attached) >= MAX_ATTACHMENTS:
        raise ApiError(
            "VALIDATION_ERROR",
            f"A conversation can have at most {MAX_ATTACHMENTS} attached inspections. "
            "Remove one before attaching another.",
            422,
        )

    attached.append(str(inspection_id))
    # Reassigned rather than mutated in place: SQLAlchemy does not track in-place changes to a
    # plain JSONB list, so an `.append()` on the attribute would never be flushed.
    session.attached_inspection_ids = attached
    await db.commit()
    await db.refresh(session)
    return session


async def detach_inspection(
    db: AsyncSession, session: ChatSession, inspection_id: uuid.UUID
) -> ChatSession:
    attached = [value for value in session.attached_inspection_ids if value != str(inspection_id)]
    if len(attached) != len(session.attached_inspection_ids):
        session.attached_inspection_ids = attached
        await db.commit()
        await db.refresh(session)
    return session


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
