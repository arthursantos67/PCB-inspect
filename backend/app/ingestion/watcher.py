"""Watch mode (FR-03, continuous): one polling iteration over the configured watch root.

Implemented as periodic polling (driven by Celery beat, see `app/tasks/ingestion.py`) rather
than an OS-level filesystem watch (inotify/watchdog) — this keeps the mechanism a plain,
directly callable async function that tests can invoke against a temp-directory fixture
with no background process or real camera involved (NFR-08), and reuses the exact same
per-file ingestion path as the one-off scan.
"""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.ingestion import service
from app.ingestion.schemas import ScanSummary
from app.models.enums import ImageSource
from app.settings import service as settings_service


async def poll_watch_root_once(db: AsyncSession) -> ScanSummary | None:
    """Returns None when watch mode is unconfigured, paused, or the root is currently
    unreadable — the next poll simply tries again, matching a physical camera folder that
    might be temporarily offline.
    """
    watch_root_path = await settings_service.get_config_value(db, "watch_root_path")
    watch_mode_enabled = bool(
        await settings_service.get_config_value(db, "watch_mode_enabled", True)
    )
    if not watch_root_path or not watch_mode_enabled:
        return None

    try:
        return await service.scan_directory(
            db, Path(str(watch_root_path)), source=ImageSource.WATCH_FOLDER
        )
    except ApiError:
        return None
