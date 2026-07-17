import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User

MAX_PAGE_SIZE = 100


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


async def query_audit_log(
    db: AsyncSession,
    *,
    account_id: uuid.UUID | None,
    action: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    page: int,
    page_size: int,
) -> tuple[int, list[tuple[AuditLog, User | None]]]:
    """Read side of FR-16 — combinable filters by account, action, and creation-date range.
    Left-joins `User` (rather than requiring `list_active_users`) so an entry created by a
    since-removed account (soft delete, FR-02) still resolves an actor to display.
    """
    conditions = []
    if account_id is not None:
        conditions.append(AuditLog.actor_id == account_id)
    if action is not None:
        conditions.append(AuditLog.action == action)
    if date_from is not None:
        conditions.append(AuditLog.created_at >= date_from)
    if date_to is not None:
        conditions.append(AuditLog.created_at <= date_to)

    count = (
        await db.execute(select(func.count(AuditLog.id)).where(*conditions))
    ).scalar() or 0
    rows = (
        await db.execute(
            select(AuditLog, User)
            .outerjoin(User, User.id == AuditLog.actor_id)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return count, [(row[0], row[1]) for row in rows]
