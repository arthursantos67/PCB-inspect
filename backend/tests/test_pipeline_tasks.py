"""Celery infrastructure tests (FR-04): acks_late/retry configuration, transient-failure
retry-then-succeed, retry-exhausted-then-FAILED, and the run_inference no-op wiring.

Tasks are exercised via `.apply()` (Celery's built-in synchronous/eager execution), never
`.delay()` — there is no Redis broker in the test environment (see CI config), and `.apply()`
still drives the exact same retry/on_failure machinery a real worker uses.
"""

import asyncio
import uuid
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.inference.detect import RawDetection
from app.knowledge.defects import DEFECT_KNOWLEDGE_BASE
from app.models import Analysis, Detection, InspectionImage, ModelVersion
from app.models.enums import AnalysisSource, AnalysisStatus, DefectType, ImageStatus
from app.tasks.base import PipelineTask
from app.tasks.celery_app import celery_app
from app.tasks.db import task_db_session
from app.tasks.errors import TransientProcessingError
from app.tasks.pipeline import run_inference


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


async def _create_image(
    *, original_path: str, status: ImageStatus = ImageStatus.QUEUED
) -> uuid.UUID:
    async with task_db_session() as db:
        image = InspectionImage(
            source="watch_folder",
            original_path=original_path,
            checksum_sha256=uuid.uuid4().hex,
            status=status,
        )
        db.add(image)
        await db.commit()
        return image.id


async def _get_image(image_id: uuid.UUID) -> InspectionImage | None:
    async with task_db_session() as db:
        return await db.get(InspectionImage, image_id)


async def _count_detections(image_id: uuid.UUID) -> int:
    async with task_db_session() as db:
        return (
            await db.scalar(
                select(func.count()).select_from(Detection).where(Detection.image_id == image_id)
            )
        ) or 0


async def _get_detection(image_id: uuid.UUID) -> Detection | None:
    async with task_db_session() as db:
        return await db.scalar(select(Detection).where(Detection.image_id == image_id))


async def _get_analysis(image_id: uuid.UUID) -> Analysis | None:
    async with task_db_session() as db:
        return await db.scalar(select(Analysis).where(Analysis.image_id == image_id))


async def _count_analyses(image_id: uuid.UUID) -> int:
    async with task_db_session() as db:
        return (
            await db.scalar(
                select(func.count()).select_from(Analysis).where(Analysis.image_id == image_id)
            )
        ) or 0


async def _seed_active_model_version(version: str = "v1.0.0") -> uuid.UUID:
    async with task_db_session() as db:
        model_version = ModelVersion(
            version=version, weights_path="/weights/best.pt", is_active=True
        )
        db.add(model_version)
        await db.commit()
        return model_version.id


class _FakeYOLO:
    """Stands in for `ultralytics.YOLO` in tests that drive `run_inference` end-to-end:
    never touches real weights, and records how many times it's constructed so warm start
    (RV-01) can be asserted directly.
    """

    instances: list["_FakeYOLO"] = []

    def __init__(self, weights_path: str) -> None:
        self.weights_path = weights_path
        type(self).instances.append(self)

    def to(self, device: str) -> "_FakeYOLO":
        self.device = device
        return self


def _stub_inference(monkeypatch: pytest.MonkeyPatch, detections: list[RawDetection]) -> None:
    monkeypatch.setattr("app.inference.model._yolo_class", lambda: _FakeYOLO)
    monkeypatch.setattr("app.inference.service.detect", lambda *args, **kwargs: detections)


def teardown_function() -> None:
    _FakeYOLO.instances = []

    async def _truncate() -> None:
        async with task_db_session() as db:
            await db.execute(text("TRUNCATE TABLE inspection_image RESTART IDENTITY CASCADE"))
            await db.execute(text("TRUNCATE TABLE model_version RESTART IDENTITY CASCADE"))
            await db.commit()

    _run(_truncate())


# --- Worker restart safety (acks_late) --------------------------------------------------------


def test_pipeline_tasks_ack_late_and_requeue_on_worker_loss() -> None:
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert run_inference.acks_late is True
    assert run_inference.reject_on_worker_lost is True


# --- run_inference: reaches PROCESSING (Enqueue on Ingestion, task side) ----------------------


def test_run_inference_reaches_completed_with_no_reportable_detections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-05's no-defect path: PROCESSING -> COMPLETED directly, skipping DETECTED. No
    `Analysis` row is ever created for it (Issue 7's No-Defect Path acceptance criterion).
    """
    _stub_inference(monkeypatch, detections=[])
    _run(_seed_active_model_version())

    image_path = tmp_path / "board.jpg"
    image_path.write_bytes(b"fake-image-bytes")
    image_id = _run(_create_image(original_path=str(image_path)))

    run_inference.apply(args=[str(image_id)])

    image = _run(_get_image(image_id))
    assert image is not None
    assert image.status == ImageStatus.COMPLETED
    assert image.annotated_path is None
    assert image.failure_reason is None
    assert len(_FakeYOLO.instances) == 1  # warm start: the model is loaded exactly once (RV-01)
    assert _run(_count_analyses(image_id)) == 0


def test_run_inference_is_idempotent_on_redelivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worker Restart Safety (acks_late): a task can be redelivered after already committing
    its terminal transition. Re-running it must not fail or reprocess the image — the guard
    is `image.status is not PROCESSING`, checked before detection ever runs again.
    """
    bbox = {"x1": 0.1, "y1": 0.1, "x2": 0.5, "y2": 0.5}
    _stub_inference(
        monkeypatch,
        detections=[RawDetection(defect_type="short", confidence=0.9, bbox=bbox)],
    )
    _run(_seed_active_model_version())
    monkeypatch.setattr(
        "app.tasks.pipeline.get_settings",
        lambda: get_settings().model_copy(update={"app_data_dir": tmp_path}),
    )

    image_path = tmp_path / "board.jpg"
    Image.new("RGB", (64, 64), (0, 0, 0)).save(image_path, format="JPEG")
    image_id = _run(_create_image(original_path=str(image_path)))

    run_inference.apply(args=[str(image_id)])
    result = run_inference.apply(args=[str(image_id)])

    assert not result.failed()
    image = _run(_get_image(image_id))
    assert image is not None
    # A reportable detection drives the image all the way to COMPLETED in one task run — the
    # baseline analysis (Issue 7) is synchronous, so there's no ANALYZING stopover to observe.
    assert image.status == ImageStatus.COMPLETED
    assert image.failure_reason is None
    assert _run(_count_detections(image_id)) == 1  # not duplicated by the redelivered attempt
    assert _run(_count_analyses(image_id)) == 1  # not duplicated by the redelivered attempt


# --- Baseline analysis generation (FR-06's baseline tier, Issue 7) ----------------------------


def test_run_inference_creates_baseline_analysis_for_reportable_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bbox = {"x1": 0.1, "y1": 0.1, "x2": 0.5, "y2": 0.5}
    _stub_inference(
        monkeypatch,
        detections=[RawDetection(defect_type="mouse_bite", confidence=0.9, bbox=bbox)],
    )
    _run(_seed_active_model_version())
    monkeypatch.setattr(
        "app.tasks.pipeline.get_settings",
        lambda: get_settings().model_copy(update={"app_data_dir": tmp_path}),
    )

    image_path = tmp_path / "board.jpg"
    Image.new("RGB", (64, 64), (0, 0, 0)).save(image_path, format="JPEG")
    image_id = _run(_create_image(original_path=str(image_path)))

    run_inference.apply(args=[str(image_id)])

    image = _run(_get_image(image_id))
    assert image is not None
    assert image.status == ImageStatus.COMPLETED  # instant availability, no ANALYZING (NFR-01)

    analysis = _run(_get_analysis(image_id))
    assert analysis is not None
    assert analysis.source == AnalysisSource.KNOWLEDGE_BASE
    assert analysis.status == AnalysisStatus.COMPLETED
    entry = DEFECT_KNOWLEDGE_BASE[DefectType.MOUSE_BITE]
    assert analysis.severity_max == entry.severity
    assert analysis.per_defect is not None
    assert analysis.per_defect[0]["description"] == entry.description
    assert analysis.per_defect[0]["severity"] == entry.severity.value

    # Regression: `process_image` must flush before returning the reportable `Detection`
    # rows — without it, `Detection.id` (a Python-side `uuid.uuid4` default applied at
    # INSERT time) is still `None` when the baseline analysis stamps `detection_id`, and
    # every consumer that parses `per_defect` as `AnalysisOut` (e.g. `GET
    # /api/v1/inspections/{id}`, FE-03) 500s trying to parse the literal string "None" as a
    # UUID. Only caught by driving the real task end to end, not the unit-level helpers in
    # test_inference.py that flush manually before calling `create_baseline_analysis`.
    detection = _run(_get_detection(image_id))
    assert detection is not None
    assert analysis.per_defect[0]["detection_id"] == str(detection.id)


# --- Retry behavior and failure isolation -----------------------------------------------------


_attempt_counts: dict[str, int] = {}


def _record_attempt(inspection_image_id: str) -> int:
    _attempt_counts[inspection_image_id] = _attempt_counts.get(inspection_image_id, 0) + 1
    return _attempt_counts[inspection_image_id]


@celery_app.task(bind=True, base=PipelineTask, name="tests.pipeline.transient_then_succeed")
def _transient_then_succeed(self: PipelineTask, inspection_image_id: str, fail_times: int) -> str:
    if self.request.retries < fail_times:
        raise TransientProcessingError("transient glitch")
    return "ok"


@celery_app.task(bind=True, base=PipelineTask, name="tests.pipeline.always_transient")
def _always_transient(self: PipelineTask, inspection_image_id: str) -> None:
    _record_attempt(inspection_image_id)
    raise TransientProcessingError("persistent LLM outage")


@celery_app.task(bind=True, base=PipelineTask, name="tests.pipeline.permanent_failure")
def _permanent_failure(self: PipelineTask, inspection_image_id: str) -> None:
    _record_attempt(inspection_image_id)
    raise ValueError("not a transient error")


def test_transient_failure_retries_then_succeeds(tmp_path: Path) -> None:
    image_path = tmp_path / "board.jpg"
    image_path.write_bytes(b"fake-image-bytes")
    image_id = _run(_create_image(original_path=str(image_path)))

    result = _transient_then_succeed.apply(args=[str(image_id), 2])

    assert result.get() == "ok"
    image = _run(_get_image(image_id))
    assert image is not None
    assert image.status == ImageStatus.QUEUED  # untouched by a task that never calls transition()


def test_transient_failure_retries_up_to_three_times_then_marks_failed(tmp_path: Path) -> None:
    image_path = tmp_path / "board.jpg"
    original_bytes = b"fake-image-bytes"
    image_path.write_bytes(original_bytes)
    image_id = _run(_create_image(original_path=str(image_path)))

    result = _always_transient.apply(args=[str(image_id)])

    assert result.failed()
    assert _attempt_counts[str(image_id)] == 4  # 1 initial attempt + 3 retries

    image = _run(_get_image(image_id))
    assert image is not None
    assert image.status == ImageStatus.FAILED
    assert image.failure_reason == "persistent LLM outage"
    # Failure isolation: the original file on disk is never touched (section 3.5).
    assert image_path.read_bytes() == original_bytes


def test_permanent_failure_is_not_retried(tmp_path: Path) -> None:
    image_path = tmp_path / "board.jpg"
    original_bytes = b"fake-image-bytes"
    image_path.write_bytes(original_bytes)
    image_id = _run(_create_image(original_path=str(image_path)))

    result = _permanent_failure.apply(args=[str(image_id)])

    assert result.failed()
    assert _attempt_counts[str(image_id)] == 1  # never retried — not a TransientProcessingError

    image = _run(_get_image(image_id))
    assert image is not None
    assert image.status == ImageStatus.FAILED
    assert image.failure_reason == "not a transient error"
    assert image_path.read_bytes() == original_bytes


def test_on_failure_does_not_raise_when_image_already_completed(tmp_path: Path) -> None:
    """`on_failure` persisting FAILED is best-effort: if the image already reached a terminal
    status through another path, `mark_failed` raises `InvalidTransitionError` — that must be
    swallowed (and logged), not escape from inside Celery's own failure-handling callback and
    mask the task's real exception.
    """
    image_path = tmp_path / "board.jpg"
    image_path.write_bytes(b"fake-image-bytes")
    image_id = _run(_create_image(original_path=str(image_path), status=ImageStatus.COMPLETED))

    result = _permanent_failure.apply(args=[str(image_id)])

    assert result.failed()  # the task's own failure is still reported
    image = _run(_get_image(image_id))
    assert image is not None
    assert image.status == ImageStatus.COMPLETED  # left untouched, not silently overwritten
