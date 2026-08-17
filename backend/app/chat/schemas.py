import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.enums import ChatRole


class ChatSessionCreate(BaseModel):
    """`POST /api/v1/chat/sessions` body. `context_analysis_id`, when set, scopes the session
    to that analysis (FE-03's "Ask about this analysis" entry point) — must reference an
    analysis that exists (validated by the router).
    """

    context_analysis_id: uuid.UUID | None = None


class ChatSessionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    title: str | None
    context_analysis_id: uuid.UUID | None
    attached_inspection_ids: list[str] = []
    created_at: datetime
    updated_at: datetime


class ChatAttachmentCreate(BaseModel):
    """`POST /api/v1/chat/sessions/{id}/attachments` body — pins one inspection's analysis to
    the conversation.
    """

    inspection_id: uuid.UUID


class ChatAttachmentOut(BaseModel):
    """An attached inspection, with the labels the chat screen shows on its chip."""

    inspection_id: uuid.UUID
    batch_number: str | None
    board_number: str | None


class ChatSessionAttachments(BaseModel):
    results: list[ChatAttachmentOut]


class ChatMessageOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    role: ChatRole
    content: str
    tool_calls: list[dict[str, Any]] | None
    created_at: datetime


class ChatSessionDetail(ChatSessionOut):
    messages: list[ChatMessageOut]


class ChatMessageCreate(BaseModel):
    content: str


class PaginatedChatSessions(BaseModel):
    results: list[ChatSessionOut]
