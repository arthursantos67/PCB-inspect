"""Generic dynamic configuration store (FR-13), backed by `SystemConfig`.

Only the ingestion-relevant keys (`watch_root_path`, `watch_mode_enabled`, `import_max_size_mb`)
are meaningfully read/written today (issue 4); later issues add thresholds, LLM settings, etc.
without needing to reshape this endpoint.
"""

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.models import SystemConfig

# Keys that must pass the invalid-path guard (PATH_NOT_FOUND/PATH_NOT_READABLE) before being
# persisted — see FE-05 (no native folder picker, so the backend is the source of truth).
_PATH_KEYS = {"watch_root_path"}


async def get_config_value(db: AsyncSession, key: str, default: Any = None) -> Any:
    config = await db.get(SystemConfig, key)
    if config is None:
        return default
    return config.value


async def get_all_config(db: AsyncSession) -> dict[str, Any]:
    result = await db.scalars(select(SystemConfig))
    return {entry.key: ("configured" if entry.is_secret else entry.value) for entry in result}


async def update_config(
    db: AsyncSession, *, actor_id: uuid.UUID, updates: dict[str, Any]
) -> dict[str, Any]:
    from app.ingestion.service import validate_directory_path  # avoids a service import cycle

    for key, value in updates.items():
        if key in _PATH_KEYS and value:
            await validate_directory_path(Path(str(value)))

        config = await db.get(SystemConfig, key)
        if config is None:
            db.add(SystemConfig(key=key, value=value, updated_by=actor_id))
        else:
            config.value = value
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
