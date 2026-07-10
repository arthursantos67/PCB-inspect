import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def record_audit(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditLog:
    """Stages an immutable AuditLog row (FR-16). Caller is responsible for committing."""
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
    )
    db.add(entry)
    await db.flush()
    return entry
