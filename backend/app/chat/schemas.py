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
    created_at: datetime
    updated_at: datetime


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
