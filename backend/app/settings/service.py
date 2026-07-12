"""Generic dynamic configuration store (FR-13), backed by `SystemConfig`.

Covers every value FR-13 requires at runtime: confidence thresholds, LLM connection, the
agent analysis policy and its trigger criteria, quality alert thresholds, the watch root
path/naming convention, retention, and the reports/exports output directory — see
`config_schema.py` for the full key registry and per-key validation.
"""

import os
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.core.config import get_settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.errors import ApiError
from app.models import SystemConfig
from app.settings.config_schema import validate_config_value

# Keys that must pass the invalid-path guard (PATH_NOT_FOUND/PATH_NOT_READABLE) before being
# persisted — see FE-05 (no native folder picker, so the backend is the source of truth).
_PATH_KEYS = {"watch_root_path"}

# Keys that are app-owned output directories, not camera-written input — created on demand
# rather than required to pre-exist (unlike `_PATH_KEYS`).
_WRITABLE_DIR_KEYS = {"reports_output_dir"}

# Keys stored encrypted (FR-13, `SystemConfig.is_secret`) — cloud LLM API keys, never returned
# in cleartext by GET /api/v1/settings/config.
_SECRET_KEYS = {"llm.api_key"}


def _ensure_writable_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if not os.access(path, os.W_OK):
        raise ApiError("PATH_NOT_WRITABLE", f"Path is not writable: {path}", 422)


def _encrypt_for_storage(value: Any) -> dict[str, str | None]:
    """`SystemConfig.value` for a secret key is `{"ciphertext": ..., "last4": ...}` rather than
    the raw scalar — `last4` is stored in the clear alongside the ciphertext so masked display
    (`get_all_config`) never has to decrypt just to render the status the API exposes.
    """
    if not value:
        return {"ciphertext": None, "last4": None}
    plaintext = str(value)
    return {"ciphertext": encrypt_secret(get_settings(), plaintext), "last4": plaintext[-4:]}


async def get_config_value(db: AsyncSession, key: str, default: Any = None) -> Any:
    config = await db.get(SystemConfig, key)
    if config is None:
        return default
    return config.value


async def get_secret_config_value(db: AsyncSession, key: str) -> str | None:
    """Decrypts a secret `SystemConfig` value for actual use (e.g. an LLM client) — `None` if
    unset. Never used to satisfy an API response; `GET /settings/config` always goes through
    `get_all_config`'s masked form instead.
    """
    config = await db.get(SystemConfig, key)
    if config is None or not config.is_secret:
        return None
    ciphertext = config.value.get("ciphertext")
    if ciphertext is None:
        return None
    return decrypt_secret(get_settings(), ciphertext)


async def get_all_config(db: AsyncSession) -> dict[str, Any]:
    result = await db.scalars(select(SystemConfig))
    config: dict[str, Any] = {}
    for entry in result:
        if entry.is_secret:
            config[entry.key] = {
                "configured": bool(entry.value.get("ciphertext")),
                "last4": entry.value.get("last4"),
            }
        else:
            config[entry.key] = entry.value
    return config


async def update_config(
    db: AsyncSession, *, actor_id: uuid.UUID, updates: dict[str, Any]
) -> dict[str, Any]:
    from app.ingestion.service import validate_directory_path  # avoids a service import cycle

    # Validate every key up front — a batch with one bad key rejects atomically rather than
    # partially applying (nothing below this point does I/O until the loop that follows).
    normalized = {key: validate_config_value(key, value) for key, value in updates.items()}

    for key, value in normalized.items():
        if key in _PATH_KEYS and value:
            await validate_directory_path(Path(str(value)))
        if key in _WRITABLE_DIR_KEYS and value:
            _ensure_writable_dir(Path(str(value)))

        is_secret = key in _SECRET_KEYS
        stored_value = _encrypt_for_storage(value) if is_secret else value

        config = await db.get(SystemConfig, key)
        if config is None:
            db.add(
                SystemConfig(key=key, value=stored_value, is_secret=is_secret, updated_by=actor_id)
            )
        else:
            config.value = stored_value
            config.is_secret = is_secret
            config.updated_by = actor_id

    await record_audit(
        db,
        actor_id=actor_id,
        action="config.updated",
        entity_type="system_config",
        payload={"keys": list(updates.keys())},
    )
    await db.commit()
    return await get_all_config(db)
