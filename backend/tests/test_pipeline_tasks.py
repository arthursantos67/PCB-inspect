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

from sqlalchemy import text

from app.models import InspectionImage
from app.models.enums import ImageStatus
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


def teardown_function() -> None:
    async def _truncate() -> None:
        async with task_db_session() as db:
            await db.execute(text("TRUNCATE TABLE inspection_image RESTART IDENTITY CASCADE"))
            await db.commit()

    _run(_truncate())


# --- Worker restart safety (acks_late) --------------------------------------------------------


def test_pipeline_tasks_ack_late_and_requeue_on_worker_loss() -> None:
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert run_inference.acks_late is True
    assert run_inference.reject_on_worker_lost is True


# --- run_inference: reaches PROCESSING (Enqueue on Ingestion, task side) ----------------------


def test_run_inference_transitions_queued_to_processing(tmp_path: Path) -> None:
    image_path = tmp_path / "board.jpg"
    image_path.write_bytes(b"fake-image-bytes")
    image_id = _run(_create_image(original_path=str(image_path)))

    run_inference.apply(args=[str(image_id)])

    image = _run(_get_image(image_id))
    assert image is not None
    assert image.status == ImageStatus.PROCESSING
    assert image.failure_reason is None


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
