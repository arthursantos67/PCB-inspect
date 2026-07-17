import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditActorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str


class AuditLogOut(BaseModel):
    id: int
    actor: AuditActorOut | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    payload: dict[str, Any] | None
    created_at: datetime


class PaginatedAuditLog(BaseModel):
    """Pagination envelope per PRD section 11.1, same shape as `PaginatedAlerts`."""

    count: int
    next: str | None
    previous: str | None
    results: list[AuditLogOut]
