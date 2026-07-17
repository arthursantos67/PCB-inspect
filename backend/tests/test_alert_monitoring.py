"""Threshold evaluation task (FR-19) — the real path. Runs `app.alerts.service.evaluate_thresholds`
directly against `task_db_session()` (same convention as `test_report_generation.py`), and the
Celery task wrapper via `.apply()` for the SSE-emission behavior.

Acceptance criteria covered:
- Threshold Crossing Detected: over-threshold produces exactly one active alert.
- No Alert Storm: an already-active or already-acknowledged-but-still-over-threshold condition
  never produces a duplicate; re-arming requires observing the rate drop back under threshold.
- SSE Event Fires: `alert.defect_rate` is published only when a new alert is actually created.
"""

import asyncio
import uuid
from collections.abc import Coroutine
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text

from app.alerts.service import acknowledge_alert, evaluate_thresholds
from app.core.security import hash_password
from app.models import Batch, Board, Detection, InspectionImage, QualityAlert, SystemConfig, User
from app.models.enums import DefectType, ImageSource, ImageStatus, QualityAlertType
from app.tasks.alert_monitor import evaluate_thresholds as evaluate_thresholds_task
from app.tasks.db import task_db_session


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


async def _set_config(threshold: float, window_minutes: int = 1440) -> None:
    async with task_db_session() as db:
        db.add(SystemConfig(key="alert_defect_rate_threshold", value=threshold))
        db.add(SystemConfig(key="alert_window_minutes", value=window_minutes))
        await db.commit()


async def _create_user() -> uuid.UUID:
    async with task_db_session() as db:
        user = User(
            email=f"{uuid.uuid4()}@pcb-inspect.local",
            password_hash=hash_password("correct-horse-battery"),
            full_name="Operator",
        )
        db.add(user)
        await db.commit()
        return user.id


async def _seed_batch(*, batch_number: str, defect_count: int, good_count: int) -> uuid.UUID:
    """A batch with `defect_count` completed images with a reported defect and `good_count`
    completed images with none — all created "now" so they fall inside any reasonable
    `alert_window_minutes` lookback.
    """
    async with task_db_session() as db:
        batch = Batch(batch_number=batch_number)
        db.add(batch)
        await db.flush()
        board = Board(batch_id=batch.id, board_number=f"{batch_number}-1")
        db.add(board)
        await db.flush()

        for _ in range(defect_count):
            image = InspectionImage(
                board_id=board.id,
                source=ImageSource.WATCH_FOLDER,
                original_path=f"/tmp/{uuid.uuid4()}.jpg",
                checksum_sha256=uuid.uuid4().hex,
                status=ImageStatus.COMPLETED,
                created_at=_now_utc(),
            )
            db.add(image)
            await db.flush()
            db.add(
                Detection(
                    image_id=image.id,
                    defect_type=DefectType.SHORT,
                    bbox={"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4},
                    confidence=Decimal("0.900"),
                    is_reported=True,
                )
            )

        for _ in range(good_count):
            image = InspectionImage(
                board_id=board.id,
                source=ImageSource.WATCH_FOLDER,
                original_path=f"/tmp/{uuid.uuid4()}.jpg",
                checksum_sha256=uuid.uuid4().hex,
                status=ImageStatus.COMPLETED,
                created_at=_now_utc(),
            )
            db.add(image)

        await db.commit()
        return batch.id


async def _run_evaluation() -> list[uuid.UUID]:
    async with task_db_session() as db:
        new_alerts = await evaluate_thresholds(db)
        return [alert.id for alert in new_alerts]


async def _alerts_for_scope(scope_key: str) -> list[QualityAlert]:
    async with task_db_session() as db:
        rows = (
            await db.execute(
                select(QualityAlert)
                .where(QualityAlert.scope_key == scope_key)
                .order_by(QualityAlert.created_at.asc())
            )
        ).scalars()
        return list(rows)


_TABLES_IN_FK_ORDER = (
    "quality_alert",
    "detection",
    "inspection_image",
    "board",
    "batch",
    "audit_log",
    "system_config",
    '"user"',
)


def teardown_function() -> None:
    async def _truncate() -> None:
        async with task_db_session() as db:
            for table in _TABLES_IN_FK_ORDER:
                await db.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
            await db.commit()

    _run(_truncate())


# --- Threshold crossing -----------------------------------------------------------------


def test_batch_over_threshold_produces_exactly_one_active_alert() -> None:
    _run(_set_config(threshold=0.5))
    batch_id = _run(_seed_batch(batch_number="BATCH-A", defect_count=2, good_count=1))
    # Dilutes the global window well under threshold so only BATCH-A's own scope is exercised
    # here — the window scope's alert is covered separately by `test_window_scope_alerts_...`.
    _run(_seed_batch(batch_number="DILUTE", defect_count=0, good_count=20))

    new_ids = _run(_run_evaluation())

    assert len(new_ids) == 1
    alerts = _run(_alerts_for_scope(str(batch_id)))
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.type == QualityAlertType.DEFECT_RATE_BATCH
    assert alert.acknowledged_at is None
    assert alert.context["threshold"] == 0.5
    assert round(alert.context["observed_rate"], 3) == round(2 / 3, 3)
    assert alert.context["batch_number"] == "BATCH-A"
    assert _run(_alerts_for_scope("global")) == []


def test_second_poll_cycle_does_not_duplicate_the_active_alert() -> None:
    _run(_set_config(threshold=0.5))
    batch_id = _run(_seed_batch(batch_number="BATCH-A", defect_count=2, good_count=1))
    _run(_seed_batch(batch_number="DILUTE", defect_count=0, good_count=20))

    first_new_ids = _run(_run_evaluation())
    second_new_ids = _run(_run_evaluation())

    assert len(first_new_ids) == 1
    assert second_new_ids == []
    alerts = _run(_alerts_for_scope(str(batch_id)))
    assert len(alerts) == 1


def test_rate_at_threshold_does_not_alert() -> None:
    _run(_set_config(threshold=0.5))
    batch_id = _run(_seed_batch(batch_number="BATCH-A", defect_count=1, good_count=1))

    new_ids = _run(_run_evaluation())

    assert new_ids == []
    assert _run(_alerts_for_scope(str(batch_id))) == []
    assert _run(_alerts_for_scope("global")) == []


def test_window_scope_alerts_across_batches() -> None:
    _run(_set_config(threshold=0.4))
    _run(_seed_batch(batch_number="BATCH-A", defect_count=1, good_count=0))
    _run(_seed_batch(batch_number="BATCH-B", defect_count=0, good_count=3))
    # Global: 1 defect out of 4 completed = 0.25, under threshold — no window alert yet.
    assert _run(_run_evaluation()) != []  # the per-batch alert for BATCH-A (rate 1.0) still fires

    window_alerts = _run(_alerts_for_scope("global"))
    assert window_alerts == []

    _run(_seed_batch(batch_number="BATCH-C", defect_count=3, good_count=0))
    # Global now: 4 defects out of 7 completed ≈ 0.571 > 0.4.
    _run(_run_evaluation())

    window_alerts = _run(_alerts_for_scope("global"))
    assert len(window_alerts) == 1
    assert window_alerts[0].type == QualityAlertType.DEFECT_RATE_WINDOW


# --- No Alert Storm / re-arm -------------------------------------------------------------


def test_acknowledged_alert_still_over_threshold_does_not_refire() -> None:
    _run(_set_config(threshold=0.5))
    batch_id = _run(_seed_batch(batch_number="BATCH-A", defect_count=2, good_count=1))
    _run(_run_evaluation())
    user_id = _run(_create_user())

    async def _ack() -> None:
        async with task_db_session() as db:
            alerts = await db.execute(
                text("SELECT id FROM quality_alert WHERE scope_key = :scope"),
                {"scope": str(batch_id)},
            )
            alert_id = alerts.scalar_one()
            await acknowledge_alert(db, actor_id=user_id, alert_id=alert_id)

    _run(_ack())

    # Still over threshold on the next poll — must not refire (AC: No Alert Storm).
    new_ids = _run(_run_evaluation())
    assert new_ids == []
    assert len(_run(_alerts_for_scope(str(batch_id)))) == 1


def test_reacknowledged_scope_rearms_once_rate_drops_and_crosses_again() -> None:
    _run(_set_config(threshold=0.5))
    batch_id = _run(_seed_batch(batch_number="BATCH-A", defect_count=2, good_count=1))
    _run(_run_evaluation())
    user_id = _run(_create_user())

    async def _ack_latest() -> None:
        async with task_db_session() as db:
            alerts = await db.execute(
                text(
                    "SELECT id FROM quality_alert WHERE scope_key = :scope "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"scope": str(batch_id)},
            )
            alert_id = alerts.scalar_one()
            await acknowledge_alert(db, actor_id=user_id, alert_id=alert_id)

    _run(_ack_latest())

    # Dilute the batch with enough good images to drop the rate under threshold, then poll —
    # this should re-arm (clear) the scope but not create a new alert (still under threshold).
    async def _add_good_images(count: int) -> None:
        async with task_db_session() as db:
            board_id = (
                await db.execute(text("SELECT id FROM board WHERE batch_id = :b"), {"b": batch_id})
            ).scalar_one()
            for _ in range(count):
                db.add(
                    InspectionImage(
                        board_id=board_id,
                        source=ImageSource.WATCH_FOLDER,
                        original_path=f"/tmp/{uuid.uuid4()}.jpg",
                        checksum_sha256=uuid.uuid4().hex,
                        status=ImageStatus.COMPLETED,
                        created_at=_now_utc(),
                    )
                )
            await db.commit()

    _run(_add_good_images(10))  # now 2 defects / 13 completed ≈ 0.154, under 0.5
    new_ids = _run(_run_evaluation())
    assert new_ids == []
    assert len(_run(_alerts_for_scope(str(batch_id)))) == 1  # still just the one, now cleared

    # Push it back over threshold — a fresh alert is now allowed to fire.
    async def _add_defect_images(count: int) -> None:
        async with task_db_session() as db:
            board_id = (
                await db.execute(text("SELECT id FROM board WHERE batch_id = :b"), {"b": batch_id})
            ).scalar_one()
            for _ in range(count):
                image = InspectionImage(
                    board_id=board_id,
                    source=ImageSource.WATCH_FOLDER,
                    original_path=f"/tmp/{uuid.uuid4()}.jpg",
                    checksum_sha256=uuid.uuid4().hex,
                    status=ImageStatus.COMPLETED,
                    created_at=_now_utc(),
                )
                db.add(image)
                await db.flush()
                db.add(
                    Detection(
                        image_id=image.id,
                        defect_type=DefectType.SHORT,
                        bbox={"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4},
                        confidence=Decimal("0.900"),
                        is_reported=True,
                    )
                )
            await db.commit()

    _run(_add_defect_images(20))  # now 22 defects / 33 completed ≈ 0.667, over 0.5 again
    new_ids = _run(_run_evaluation())
    assert len(new_ids) == 1
    alerts = _run(_alerts_for_scope(str(batch_id)))
    assert len(alerts) == 2
    assert alerts[-1].acknowledged_at is None


# --- SSE emission (Celery task wrapper) ---------------------------------------------------


def test_task_emits_sse_event_only_for_newly_created_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[tuple[str, dict[str, Any]]] = []

    async def _fake_publish(event_type: str, data: dict[str, Any]) -> None:
        published.append((event_type, data))

    monkeypatch.setattr("app.tasks.alert_monitor.publish_event", _fake_publish)

    _run(_set_config(threshold=0.5))
    _run(_seed_batch(batch_number="BATCH-A", defect_count=2, good_count=1))
    _run(_seed_batch(batch_number="DILUTE", defect_count=0, good_count=20))

    evaluate_thresholds_task.apply()

    assert len(published) == 1
    event_type, data = published[0]
    assert event_type == "alert.defect_rate"
    assert data["type"] == "defect_rate_batch"

    published.clear()
    evaluate_thresholds_task.apply()
    assert published == []
