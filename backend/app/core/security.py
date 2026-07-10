import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


class InvalidTokenError(Exception):
    """Raised for any expired/malformed/wrong-type token — callers map this to NOT_AUTHENTICATED."""


def _create_token(user_id: uuid.UUID, token_type: TokenType, expires_delta: timedelta) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def create_access_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    return _create_token(
        user_id, "access", timedelta(minutes=settings.access_token_expire_minutes)
    )


def create_refresh_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    return _create_token(
        user_id, "refresh", timedelta(minutes=settings.refresh_token_expire_minutes)
    )


def decode_token(token: str, expected_type: TokenType) -> uuid.UUID:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if payload.get("type") != expected_type:
        raise InvalidTokenError("unexpected token type")
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError("malformed subject") from exc
