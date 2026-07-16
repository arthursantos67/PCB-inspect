"""Golden-set evaluation task orchestration and the no-downtime activation reload (FR-12).

Runs Celery tasks via `.apply()` (eager execution) — same convention as
`test_pipeline_tasks.py`; there's no Redis broker in the test environment. Uses direct
`task_db_session()` calls plus a manual `teardown_function` truncate, matching that file's
pattern, rather than the `client`/`db_session` fixtures used by `test_model_versions.py`.
"""

import asyncio
import json
import uuid
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import select, text

from app.core.config import get_settings
from app.inference.model import ensure_model_loaded, reload_active_model
from app.models import AuditLog, ModelVersion
from app.models.enums import DefectType, ModelEvaluationStatus
from app.tasks.db import task_db_session
from app.tasks.models import reload_inference_model, run_model_evaluation

CLASSES = [d.value for d in DefectType]


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


async def _create_model_version(
    *, version: str, weights_path: str = "/weights/whatever.pt", is_active: bool = False
) -> uuid.UUID:
    async with task_db_session() as db:
        model_version = ModelVersion(
            version=version, weights_path=weights_path, is_active=is_active
        )
        db.add(model_version)
        await db.commit()
        return model_version.id


async def _get_model_version(model_version_id: uuid.UUID) -> ModelVersion | None:
    async with task_db_session() as db:
        return await db.get(ModelVersion, model_version_id)


async def _set_active(model_version_id: uuid.UUID, *, active: bool) -> None:
    async with task_db_session() as db:
        model_version = await db.get(ModelVersion, model_version_id)
        assert model_version is not None
        model_version.is_active = active
        await db.commit()


async def _latest_audit(action: str) -> AuditLog | None:
    async with task_db_session() as db:
        return await db.scalar(
            select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id.desc())
        )


def teardown_function() -> None:
    async def _truncate() -> None:
        async with task_db_session() as db:
            await db.execute(text("TRUNCATE TABLE audit_log RESTART IDENTITY CASCADE"))
            await db.execute(text("TRUNCATE TABLE model_version RESTART IDENTITY CASCADE"))
            await db.commit()

    _run(_truncate())


def _write_golden_set(root: Path) -> None:
    golden_set_dir = root / "golden-set"
    image_path = golden_set_dir / "images" / "a.jpg"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (100, 100), (10, 20, 30)).save(image_path, format="JPEG")
    label_path = golden_set_dir / "labels" / "a.txt"
    label_path.parent.mkdir(parents=True)
    label_path.write_text("3 0.5 0.5 0.4 0.4\n")  # class idx 3 == "short"
    (golden_set_dir / "manifest.json").write_text(
        json.dumps(
            {
                "version": "gs-1",
                "classes": CLASSES,
                "images": [{"image": "images/a.jpg", "label": "labels/a.txt"}],
            }
        )
    )


# --- run_model_evaluation: the real path (FR-12's "Evaluation Is Real") -------------------


def test_run_model_evaluation_completes_and_records_real_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_golden_set(tmp_path)
    fake_settings = get_settings().model_copy(
        update={"app_data_dir": tmp_path, "inference_backend": "fake"}
    )
    monkeypatch.setattr("app.tasks.models.get_settings", lambda: fake_settings)
    monkeypatch.setattr("app.inference.model.get_settings", lambda: fake_settings)

    model_version_id = _run(_create_model_version(version="eval-1"))

    run_model_evaluation.apply(args=[str(model_version_id)])

    model_version = _run(_get_model_version(model_version_id))
    assert model_version is not None
    assert model_version.evaluation_status == ModelEvaluationStatus.COMPLETED
    assert model_version.evaluation_error is None
    assert model_version.metrics is not None
    assert model_version.metrics["map50"] == pytest.approx(1.0)
    assert model_version.metrics["per_class"]["short"] == pytest.approx(1.0)
    assert model_version.metrics["golden_set_version"] == "gs-1"

    audit = _run(_latest_audit("model.evaluated"))
    assert audit is not None
    assert audit.entity_id == model_version_id


def test_run_model_evaluation_without_a_golden_set_fails_gracefully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing/misconfigured golden set must degrade to a visible `FAILED` evaluation, never
    crash the worker or leave the version stuck `RUNNING` forever.
    """
    fake_settings = get_settings().model_copy(update={"app_data_dir": tmp_path})
    monkeypatch.setattr("app.tasks.models.get_settings", lambda: fake_settings)

    model_version_id = _run(_create_model_version(version="eval-2"))

    run_model_evaluation.apply(args=[str(model_version_id)])

    model_version = _run(_get_model_version(model_version_id))
    assert model_version is not None
    assert model_version.evaluation_status == ModelEvaluationStatus.FAILED
    assert model_version.evaluation_error is not None
    assert model_version.metrics is None

    audit = _run(_latest_audit("model.evaluation_failed"))
    assert audit is not None
    assert audit.entity_id == model_version_id


# --- No-downtime activation switch (FR-12) -------------------------------------------------


class _CountingFakeYOLO:
    instances = 0

    def __init__(self, weights_path: str) -> None:
        self.weights_path = weights_path
        type(self).instances += 1

    def to(self, device: str) -> "_CountingFakeYOLO":
        self.device = device
        return self


def test_reload_active_model_never_invalidates_a_reference_already_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mechanism behind FR-12's "No-Downtime Switch" acceptance criterion: an in-flight
    `run_inference` task calls `ensure_model_loaded()` once and keeps that exact `LoadedModel`
    object for the rest of its own execution. Activating a new version must never mutate that
    object out from under it — only ever swap which object *future* calls receive.
    """
    monkeypatch.setattr("app.inference.model._yolo_class", lambda: _CountingFakeYOLO)
    _CountingFakeYOLO.instances = 0

    v1_id = _run(_create_model_version(version="reload-v1", is_active=True))
    v2_id = _run(_create_model_version(version="reload-v2", is_active=False))

    loaded_v1 = _run(ensure_model_loaded())
    assert loaded_v1.model_version_id == v1_id

    # Simulates `activate_model_version` having already committed the switch.
    _run(_set_active(v1_id, active=False))
    _run(_set_active(v2_id, active=True))

    reloaded = _run(reload_active_model())

    # The reference an in-flight task already grabbed is completely unaffected.
    assert loaded_v1.model_version_id == v1_id
    assert reloaded.model_version_id == v2_id
    # Any call after the reload — i.e. the next task — sees the new version.
    assert _run(ensure_model_loaded()) is reloaded
    assert _CountingFakeYOLO.instances == 2  # v1 warm start + the v2 reload, never more


def test_reload_inference_model_task_swaps_to_the_new_active_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.inference.model._yolo_class", lambda: _CountingFakeYOLO)
    _CountingFakeYOLO.instances = 0

    v1_id = _run(_create_model_version(version="reload-task-v1", is_active=True))
    _run(ensure_model_loaded())
    v2_id = _run(_create_model_version(version="reload-task-v2", is_active=False))
    _run(_set_active(v1_id, active=False))
    _run(_set_active(v2_id, active=True))

    reload_inference_model.apply()

    assert _run(ensure_model_loaded()).model_version_id == v2_id
