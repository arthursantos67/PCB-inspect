import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChatSession(Base):
    """A persistent chat session per local account (FR-09). `context_analysis_id` is set when
    the session was opened from an analysis detail screen's "Ask about this analysis" entry
    point (FE-03) so the first turn already has that inspection in context without the
    operator re-typing which board they mean.

    `attached_inspection_ids` is the operator-driven counterpart: inspections pinned to the
    conversation by hand from the chat screen, re-sent as tool results on every turn. Kept as
    a plain id list rather than a join table because nothing queries it in reverse — it is
    only ever read for the session it belongs to — and ids whose inspection is gone are
    skipped when the context is built (`app.chat.agent`).
    """

    __tablename__ = "chat_session"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(nullable=True)
    context_analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis.id"), nullable=True
    )
    attached_inspection_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
