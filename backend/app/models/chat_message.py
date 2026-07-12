import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ChatRole, pg_enum


class ChatMessage(Base):
    """One turn of a `ChatSession` (FR-09, PRD 10.2). `tool_calls` records the tools invoked to
    produce an `assistant` message's content — the durable evidence backing the "Tool-Only
    Facts" acceptance criterion (issue #32): every factual claim about production data must be
    traceable to a tool call recorded here, never asserted from the model's own memory.
    """

    __tablename__ = "chat_message"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_session.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[ChatRole] = mapped_column(pg_enum(ChatRole, "chat_role"), nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
