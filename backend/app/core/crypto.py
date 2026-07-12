"""Symmetric encryption for sensitive `SystemConfig` values (FR-13) — e.g. cloud LLM API keys.

Keyed off `settings.secret_key` (SHA-256'd into a valid Fernet key), the same setting used to
sign session tokens (`app.core.security`) — so rotating `secret_key` invalidates previously
encrypted secrets exactly like it invalidates existing sessions. That trade-off is accepted
rather than managing a separate encryption key.
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings

__all__ = ["InvalidToken", "decrypt_secret", "encrypt_secret"]


def _derive_key(secret_key: str) -> bytes:
    digest = hashlib.sha256(secret_key.encode()).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache
def _fernet(secret_key: str) -> Fernet:
    return Fernet(_derive_key(secret_key))


def encrypt_secret(settings: Settings, plaintext: str) -> str:
    return _fernet(settings.secret_key).encrypt(plaintext.encode()).decode()


def decrypt_secret(settings: Settings, token: str) -> str:
    return _fernet(settings.secret_key).decrypt(token.encode()).decode()
