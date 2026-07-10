from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.security import InvalidTokenError, decode_token
from app.db.session import get_db
from app.models import User

_bearer_scheme = HTTPBearer(auto_error=False)


def _not_authenticated() -> ApiError:
    return ApiError("NOT_AUTHENTICATED", "Missing or expired session.", 401)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """No role check here or anywhere else — every authenticated account is equal (PRD 2.2)."""
    if credentials is None:
        raise _not_authenticated()
    try:
        user_id = decode_token(credentials.credentials, "access")
    except InvalidTokenError as exc:
        raise _not_authenticated() from exc

    user = await db.get(User, user_id)
    if user is None or user.deactivated_at is not None:
        raise _not_authenticated()
    return user
