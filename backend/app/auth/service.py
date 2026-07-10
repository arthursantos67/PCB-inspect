from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models import User

_INVALID_CREDENTIALS = ApiError("INVALID_CREDENTIALS", "Invalid email or password.", 401)


async def any_account_exists(db: AsyncSession) -> bool:
    count = await db.scalar(select(func.count()).select_from(User))
    return bool(count)


async def create_initial_account(
    db: AsyncSession, *, email: str, password: str, full_name: str
) -> User:
    # Re-checked here (not just at the route) to close the race between two concurrent
    # first-run setup requests — only one may win.
    if await any_account_exists(db):
        raise ApiError(
            "SETUP_ALREADY_COMPLETED", "An account already exists on this install.", 409
        )
    user = User(email=email, password_hash=hash_password(password), full_name=full_name)
    db.add(user)
    await db.flush()
    await record_audit(
        db,
        actor_id=user.id,
        action="account.created",
        entity_type="user",
        entity_id=user.id,
        payload={"email": email, "via": "setup"},
    )
    await db.commit()
    await db.refresh(user)
    return user


def _lockout_seconds(failed_attempts: int) -> int:
    settings = get_settings()
    if failed_attempts < settings.max_failed_login_attempts:
        return 0
    overflow = failed_attempts - settings.max_failed_login_attempts
    return int(min(settings.lockout_base_seconds * (2**overflow), settings.lockout_max_seconds))


async def authenticate(db: AsyncSession, *, email: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.email == email))
    if user is None or user.deactivated_at is not None:
        raise _INVALID_CREDENTIALS

    now = datetime.now(UTC)
    if user.locked_until is not None and user.locked_until > now:
        raise ApiError(
            "ACCOUNT_LOCKED",
            "Too many failed attempts. Try again later.",
            423,
            {"locked_until": user.locked_until.isoformat()},
        )

    if not verify_password(password, user.password_hash):
        user.failed_login_attempts += 1
        lockout = _lockout_seconds(user.failed_login_attempts)
        if lockout:
            user.locked_until = now + timedelta(seconds=lockout)
        await db.commit()
        raise _INVALID_CREDENTIALS

    user.failed_login_attempts = 0
    user.locked_until = None
    await record_audit(
        db, actor_id=user.id, action="user.login", entity_type="user", entity_id=user.id
    )
    await db.commit()
    await db.refresh(user)
    return user


def issue_tokens(user: User) -> tuple[str, str, int]:
    settings = get_settings()
    access = create_access_token(user.id)
    refresh = create_refresh_token(user.id)
    return access, refresh, settings.access_token_expire_minutes * 60


async def user_from_refresh_token(db: AsyncSession, *, refresh_token: str) -> User:
    invalid = ApiError("NOT_AUTHENTICATED", "Invalid or expired refresh token.", 401)
    try:
        user_id = decode_token(refresh_token, "refresh")
    except InvalidTokenError as exc:
        raise invalid from exc

    user = await db.get(User, user_id)
    if user is None or user.deactivated_at is not None:
        raise invalid
    return user
