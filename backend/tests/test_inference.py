"""Inference stage tests (FR-05): threshold split (RV-03), Detection persistence with model
version traceability (RV-05), annotated image generation (RV-04), the no-defect path, and
warm-start model loading (RV-01/RV-02).

Runs against the real Postgres schema (constraints matter — see conftest.py) with the YOLO
forward pass replaced by a fixture-controlled `detect()` stub: there's no tracked model
weight file for CI to load (README — `weights/best.pt` isn't in git) and no GPU on CI
runners, so the real Ultralytics call is only exercised in local/manual verification.
"""

import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.inference.annotate import write_annotated_image
from app.inference.detect import RawDetection, detect
from app.inference.model import LoadedModel, ensure_model_loaded
from app.inference.service import process_image
from app.models import Detection, InspectionImage, ModelVersion, SystemConfig
from app.models.enums import ImageSource, ImageStatus
from app.tasks.errors import TransientProcessingError


async def _make_model_version(db_session: AsyncSession, version: str = "v1.0.0") -> ModelVersion:
    model_version = ModelVersion(version=version, weights_path="/weights/best.pt", is_active=True)
    db_session.add(model_version)
    await db_session.flush()
    return model_version


async def _make_image(db_session: AsyncSession, original_path: str) -> InspectionImage:
    image = InspectionImage(
        source=ImageSource.WATCH_FOLDER,
        original_path=original_path,
        checksum_sha256=uuid.uuid4().hex,
        status=ImageStatus.PROCESSING,
    )
    db_session.add(image)
    await db_session.flush()
    return image


def _loaded_model(model_version: ModelVersion) -> LoadedModel:
    return LoadedModel(
        model=object(),  # never touched — `detect()` is monkeypatched in every test below
        device="cpu",
        model_version_id=model_version.id,
        model_version=model_version.version,
    )


def _bbox(x1: float = 0.1, y1: float = 0.1, x2: float = 0.4, y2: float = 0.4) -> dict[str, float]:
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}


@pytest.fixture
def board_image(tmp_path: Path) -> Path:
    path = tmp_path / "board.jpg"
    Image.new("RGB", (100, 100), (10, 20, 30)).save(path, format="JPEG")
    return path


async def _detections(db_session: AsyncSession) -> list[Detection]:
    return list((await db_session.scalars(select(Detection))).all())


# --- Threshold split (RV-03) and the no-defect path (FR-05) ---------------------------------


async def test_detection_above_report_threshold_is_persisted_and_reported(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, board_image: Path
) -> None:
    model_version = await _make_model_version(db_session)
    image = await _make_image(db_session, str(board_image))
    monkeypatch.setattr(
        "app.inference.service.detect",
        lambda *a, **k: [RawDetection(defect_type="short", confidence=0.9, bbox=_bbox())],
    )

    await process_image(
        db_session, image, _loaded_model(model_version), app_data_dir=board_image.parent
    )
    await db_session.flush()

    detections = await _detections(db_session)
    assert len(detections) == 1
    assert detections[0].is_reported is True
    assert detections[0].confidence == Decimal("0.900")
    assert detections[0].model_version_id == model_version.id
    assert image.status == ImageStatus.DETECTED
    assert image.annotated_path is not None
    annotated = Path(image.annotated_path)
    assert annotated.exists()
    with Image.open(annotated) as annotated_img:
        assert annotated_img.size == (100, 100)  # redrawn over a copy of the source dimensions


async def test_detection_between_thresholds_is_stored_but_not_reported(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, board_image: Path
) -> None:
    """RV-03: persisted (>= store threshold) but `is_reported=False` (< report threshold)."""
    model_version = await _make_model_version(db_session)
    image = await _make_image(db_session, str(board_image))
    monkeypatch.setattr(
        "app.inference.service.detect",
        lambda *a, **k: [RawDetection(defect_type="spur", confidence=0.30, bbox=_bbox())],
    )

    await process_image(
        db_session, image, _loaded_model(model_version), app_data_dir=board_image.parent
    )
    await db_session.flush()

    detections = await _detections(db_session)
    assert len(detections) == 1
    assert detections[0].is_reported is False
    # No reportable detection: the no-defect path still applies even though a row was
    # persisted for later auditing (RV-03's rationale) — FR-05.
    assert image.status == ImageStatus.COMPLETED
    assert image.annotated_path is None


async def test_detection_below_store_threshold_is_not_persisted(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, board_image: Path
) -> None:
    model_version = await _make_model_version(db_session)
    image = await _make_image(db_session, str(board_image))
    monkeypatch.setattr(
        "app.inference.service.detect",
        lambda *a, **k: [RawDetection(defect_type="spur", confidence=0.1, bbox=_bbox())],
    )

    await process_image(
        db_session, image, _loaded_model(model_version), app_data_dir=board_image.parent
    )
    await db_session.flush()

    assert await _detections(db_session) == []
    assert image.status == ImageStatus.COMPLETED
    assert image.annotated_path is None


async def test_no_detections_reaches_completed_with_empty_defect_result(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, board_image: Path
) -> None:
    model_version = await _make_model_version(db_session)
    image = await _make_image(db_session, str(board_image))
    monkeypatch.setattr("app.inference.service.detect", lambda *a, **k: [])

    await process_image(
        db_session, image, _loaded_model(model_version), app_data_dir=board_image.parent
    )

    assert await _detections(db_session) == []
    assert image.status == ImageStatus.COMPLETED
    assert image.annotated_path is None


async def test_custom_thresholds_from_system_config_are_honored(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, board_image: Path
) -> None:
    """RV-03: both thresholds are configurable at runtime via SystemConfig, not hardcoded."""
    model_version = await _make_model_version(db_session)
    image = await _make_image(db_session, str(board_image))
    db_session.add(SystemConfig(key="min_confidence_store", value=0.5, is_secret=False))
    db_session.add(SystemConfig(key="min_confidence_report", value=0.8, is_secret=False))
    await db_session.flush()
    monkeypatch.setattr(
        "app.inference.service.detect",
        # Would be store+report under the defaults (0.25/0.50); under the raised config
        # thresholds above, 0.6 is stored-but-unreported and the image has no defect result.
        lambda *a, **k: [RawDetection(defect_type="short", confidence=0.6, bbox=_bbox())],
    )

    await process_image(
        db_session, image, _loaded_model(model_version), app_data_dir=board_image.parent
    )
    await db_session.flush()

    detections = await _detections(db_session)
    assert len(detections) == 1
    assert detections[0].is_reported is False
    assert image.status == ImageStatus.COMPLETED


async def test_annotated_image_only_draws_reportable_detections(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, board_image: Path
) -> None:
    """Regression (issue #21, item 7): a sub-`min_confidence_report` detection stored
    alongside a reportable one must never reach `write_annotated_image` — the served
    `variant=annotated` image must match exactly what `is_reported=True` exposes via the API,
    not everything persisted for audit purposes (RV-03).
    """
    model_version = await _make_model_version(db_session)
    image = await _make_image(db_session, str(board_image))
    below_report = RawDetection(defect_type="spur", confidence=0.30, bbox=_bbox())
    above_report = RawDetection(
        defect_type="short", confidence=0.9, bbox=_bbox(0.5, 0.5, 0.7, 0.7)
    )
    monkeypatch.setattr(
        "app.inference.service.detect", lambda *a, **k: [below_report, above_report]
    )
    captured: dict[str, object] = {}

    def _capturing_write(*, detections: list[RawDetection], **kwargs: Any) -> Path:
        captured["detections"] = detections
        return write_annotated_image(detections=detections, **kwargs)

    monkeypatch.setattr("app.inference.service.write_annotated_image", _capturing_write)

    await process_image(
        db_session, image, _loaded_model(model_version), app_data_dir=board_image.parent
    )
    await db_session.flush()

    assert captured["detections"] == [above_report]


async def test_multiple_detections_all_traced_to_active_model_version(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, board_image: Path
) -> None:
    model_version = await _make_model_version(db_session, version="v2.0.0")
    image = await _make_image(db_session, str(board_image))
    monkeypatch.setattr(
        "app.inference.service.detect",
        lambda *a, **k: [
            RawDetection(defect_type="short", confidence=0.9, bbox=_bbox(0.1, 0.1, 0.3, 0.3)),
            RawDetection(defect_type="spur", confidence=0.6, bbox=_bbox(0.5, 0.5, 0.7, 0.7)),
        ],
    )

    await process_image(
        db_session, image, _loaded_model(model_version), app_data_dir=board_image.parent
    )
    await db_session.flush()

    detections = await _detections(db_session)
    assert len(detections) == 2
    assert all(d.model_version_id == model_version.id for d in detections)  # RV-05


# --- Warm-start model loading (RV-01/RV-02) --------------------------------------------------


class _CountingFakeYOLO:
    instances = 0

    def __init__(self, weights_path: str) -> None:
        self.weights_path = weights_path
        type(self).instances += 1

    def to(self, device: str) -> "_CountingFakeYOLO":
        self.device = device
        return self


async def test_ensure_model_loaded_warm_starts_once_and_caches(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_version = await _make_model_version(db_session)
    await db_session.commit()  # `ensure_model_loaded` reads via a separate connection
    monkeypatch.setattr("app.inference.model._yolo_class", lambda: _CountingFakeYOLO)
    _CountingFakeYOLO.instances = 0

    first = await ensure_model_loaded()
    second = await ensure_model_loaded()

    assert first is second  # cached — no reload on the second call
    assert _CountingFakeYOLO.instances == 1
    assert first.model_version_id == model_version.id
    assert first.model_version == model_version.version
    assert first.device == "cpu"


async def test_ensure_model_loaded_raises_transient_error_without_active_version() -> None:
    with pytest.raises(TransientProcessingError):
        await ensure_model_loaded()


# --- Fake inference backend (Playwright E2E, section 14.2) -----------------------------------
#
# `settings.inference_backend == "fake"` swaps `_yolo_class()`/`_select_device()` for a
# deterministic stand-in (no `weights/best.pt`, no GPU) — unlike every test above, which
# monkeypatches `detect()` itself away, these exercise the real `detect()` contract against
# the fake model to prove the substitution actually satisfies it.


async def test_fake_inference_backend_produces_deterministic_short_detection(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, board_image: Path
) -> None:
    await _make_model_version(db_session)
    await db_session.commit()
    fake_settings = get_settings().model_copy(update={"inference_backend": "fake"})
    monkeypatch.setattr("app.inference.model.get_settings", lambda: fake_settings)

    loaded = await ensure_model_loaded()
    assert loaded.device == "cpu"

    detections = detect(loaded.model, board_image, min_confidence=0.25)

    assert len(detections) == 1
    assert detections[0].defect_type == "short"
    assert detections[0].confidence == pytest.approx(0.9)
    assert detections[0].bbox == {"x1": 0.3, "y1": 0.3, "x2": 0.7, "y2": 0.7}


async def test_fake_inference_backend_respects_confidence_floor(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, board_image: Path
) -> None:
    await _make_model_version(db_session)
    await db_session.commit()
    fake_settings = get_settings().model_copy(update={"inference_backend": "fake"})
    monkeypatch.setattr("app.inference.model.get_settings", lambda: fake_settings)

    loaded = await ensure_model_loaded()

    assert detect(loaded.model, board_image, min_confidence=0.95) == []
