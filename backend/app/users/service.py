import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.core.errors import ApiError
from app.core.security import hash_password
from app.models import User


async def list_active_users(db: AsyncSession) -> list[User]:
    result = await db.scalars(
        select(User).where(User.deactivated_at.is_(None)).order_by(User.created_at)
    )
    return list(result)


async def _email_taken(
    db: AsyncSession, email: str, *, exclude_user_id: uuid.UUID | None = None
) -> bool:
    stmt = select(User.id).where(User.email == email, User.deactivated_at.is_(None))
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    return await db.scalar(stmt) is not None


async def create_user(
    db: AsyncSession, *, actor_id: uuid.UUID, email: str, password: str, full_name: str
) -> User:
    if await _email_taken(db, email):
        raise ApiError(
            "VALIDATION_FAILED",
            "An account with this email already exists.",
            400,
            {"field": "email"},
        )
    user = User(email=email, password_hash=hash_password(password), full_name=full_name)
    db.add(user)
    await db.flush()
    await record_audit(
        db,
        actor_id=actor_id,
        action="account.created",
        entity_type="user",
        entity_id=user.id,
        payload={"email": email},
    )
    await db.commit()
    await db.refresh(user)
    return user


async def get_active_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None or user.deactivated_at is not None:
        raise ApiError("RESOURCE_NOT_FOUND", "Account not found.", 404)
    return user


async def update_user(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID,
    user_id: uuid.UUID,
    email: str | None,
    full_name: str | None,
    password: str | None,
) -> User:
    user = await get_active_user_or_404(db, user_id)

    changed_fields: list[str] = []
    if email is not None and email != user.email:
        if await _email_taken(db, email, exclude_user_id=user_id):
            raise ApiError(
                "VALIDATION_FAILED",
                "An account with this email already exists.",
                400,
                {"field": "email"},
            )
        user.email = email
        changed_fields.append("email")
    if full_name is not None and full_name != user.full_name:
        user.full_name = full_name
        changed_fields.append("full_name")
    if password is not None:
        user.password_hash = hash_password(password)
        changed_fields.append("password")

    if changed_fields:
        await record_audit(
            db,
            actor_id=actor_id,
            action="account.updated",
            entity_type="user",
            entity_id=user.id,
            payload={"fields": changed_fields},
        )
        await db.commit()
        await db.refresh(user)
    return user


async def deactivate_user(db: AsyncSession, *, actor_id: uuid.UUID, user_id: uuid.UUID) -> None:
    user = await get_active_user_or_404(db, user_id)

    active_count = await db.scalar(
        select(func.count()).select_from(User).where(User.deactivated_at.is_(None))
    )
    if active_count is not None and active_count <= 1:
        raise ApiError(
            "CANNOT_DELETE_LAST_ACCOUNT", "At least one local account must remain.", 409
        )

    user.deactivated_at = datetime.now(UTC)
    await record_audit(
        db,
        actor_id=actor_id,
        action="account.removed",
        entity_type="user",
        entity_id=user.id,
        payload={"email": user.email},
    )
    await db.commit()
