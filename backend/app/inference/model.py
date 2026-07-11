"""Warm-start YOLO11x model loading (RV-01/RV-02).

`ensure_model_loaded()` is the only entry point: the first call loads `best.pt` from the
currently active `ModelVersion` and caches it in a module-level global for the lifetime of
the worker process; every later call — whether the eager boot warm-up in
`app.tasks.pipeline` or the first inference task if that warm-up hasn't completed yet —
returns the same cached instance. A cold model load (multi-second) must never happen more
than once per process, and never inline with a per-image request beyond that first call.

`ultralytics`/`torch` are imported lazily, inside the functions below, rather than at module
scope: importing `ultralytics` globally monkey-patches `PIL.Image.open` (to add HEIC/AVIF
support) as a side effect, and only the dedicated inference worker (gated by `WORKER_ROLE`
in `app.tasks.pipeline`) is meant to ever pay for that — the API and agent-worker processes
also open images directly (ingestion validation, FR-03) and must never have that patched out
from under them just because they happen to import this module's public API.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.inference.status import publish_model_status
from app.models import ModelVersion
from app.tasks.db import task_db_session
from app.tasks.errors import TransientProcessingError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadedModel:
    model: Any  # ultralytics.YOLO — kept as Any so this module never has to import it eagerly
    device: str
    model_version_id: uuid.UUID
    model_version: str


_loaded: LoadedModel | None = None


def _yolo_class() -> Any:
    from ultralytics import YOLO

    return YOLO


def _select_device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


async def ensure_model_loaded() -> LoadedModel:
    global _loaded
    if _loaded is not None:
        return _loaded

    async with task_db_session() as db:
        active = await db.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True)))

    if active is None:
        # Environmental/startup-ordering issue (e.g. the dev seed hasn't run yet) rather
        # than a permanent one — worth a few retries (PipelineTask.autoretry_for) before
        # giving up.
        raise TransientProcessingError("No active ModelVersion is configured")

    try:
        device = _select_device()
        model = _yolo_class()(active.weights_path)
        model.to(device)
    except Exception as exc:
        raise TransientProcessingError(f"Failed to load model weights: {exc}") from exc

    loaded = LoadedModel(
        model=model, device=device, model_version_id=active.id, model_version=active.version
    )
    _loaded = loaded
    logger.info("Loaded model version=%s device=%s", active.version, device)
    await publish_model_status(get_settings(), device=device, model_version=active.version)
    return loaded


def reset_loaded_model_for_tests() -> None:
    """Test-only escape hatch — `_loaded` is process-global by design (RV-01), so tests that
    need a fresh load (e.g. to swap the active `ModelVersion` or the stubbed model class)
    must clear it explicitly between cases.
    """
    global _loaded
    _loaded = None
