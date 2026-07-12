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


class _FakeBoxScalar:
    """Mimics the `.item()` surface of an ultralytics box's `cls`/`conf` tensors."""

    def __init__(self, value: float) -> None:
        self._value = value

    def item(self) -> float:
        return self._value


class _FakeBoxCoords:
    """Mimics the `.tolist()` surface of an ultralytics box's `xyxyn[0]` tensor."""

    def __init__(self, values: list[float]) -> None:
        self._values = values

    def tolist(self) -> list[float]:
        return self._values


class _FakeBox:
    def __init__(self, cls_idx: int, confidence: float, xyxyn: list[float]) -> None:
        self.cls = _FakeBoxScalar(cls_idx)
        self.conf = _FakeBoxScalar(confidence)
        self.xyxyn = [_FakeBoxCoords(xyxyn)]


class _FakeResult:
    def __init__(self, names: dict[int, str], boxes: list[_FakeBox]) -> None:
        self.names = names
        self.boxes = boxes


class _FakeYOLO:
    """Deterministic stand-in for `ultralytics.YOLO`, used only when
    `settings.inference_backend == "fake"`. Real inference needs `weights/best.pt` (a
    114MB artifact not tracked in git, README) and CI runners have no GPU — this is what
    lets the Playwright E2E suite (NFR-08, section 14.2) exercise ingestion -> processing ->
    detail view without either. Always reports one `short` defect over the image center,
    honoring the confidence floor passed to `predict()` so RV-03's threshold split is still
    exercised end to end.
    """

    _CONFIDENCE = 0.9
    _BBOX = [0.3, 0.3, 0.7, 0.7]

    def __init__(self, weights_path: str) -> None:
        self.weights_path = weights_path

    def to(self, device: str) -> "_FakeYOLO":
        return self

    def predict(self, *, source: str, conf: float, verbose: bool = False) -> list[_FakeResult]:
        boxes = [_FakeBox(0, self._CONFIDENCE, self._BBOX)] if conf <= self._CONFIDENCE else []
        return [_FakeResult(names={0: "short"}, boxes=boxes)]


def _yolo_class() -> Any:
    if get_settings().inference_backend == "fake":
        return _FakeYOLO

    from ultralytics import YOLO

    return YOLO


def _select_device() -> str:
    if get_settings().inference_backend == "fake":
        return "cpu"

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
