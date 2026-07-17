"""Threshold evaluation and alert lifecycle (FR-19): the monitoring task's real logic
(`app.tasks.alert_monitor.evaluate_thresholds` was previously a stub) plus the list/acknowledge
operations `app.alerts.router` exposes.

RN-07: only `is_reported=true` detections count toward "this image has a reported defect",
same rule `app.stats.service` follows for every other aggregate.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.core.errors import ApiError
from app.models import Batch, Board, Detection, InspectionImage, QualityAlert
from app.models.enums import ImageStatus, QualityAlertType
from app.settings.service import get_config_value

MAX_PAGE_SIZE = 100

# `defect_rate_window` isn't scoped to any one batch, so it shares this single scope key across
# every poll — unlike `defect_rate_batch`, where each batch's UUID is its own scope key.
_GLOBAL_WINDOW_SCOPE_KEY = "global"


async def _batch_defect_rates(
    db: AsyncSession, *, since: datetime
) -> list[tuple[uuid.UUID, str, float, int]]:
    """One row per batch with at least one completed image since `since`: (batch_id,
    batch_number, defect_rate, completed_count). Scoped to recent activity so a poll doesn't
    re-scan a lifetime of already-closed-out batches — a batch with no completed images in the
    window simply isn't re-evaluated until it has more.
    """
    has_reported_defect = exists(
        select(1).where(Detection.image_id == InspectionImage.id, Detection.is_reported.is_(True))
    )
    stmt = (
        select(
            Batch.id,
            Batch.batch_number,
            func.count(InspectionImage.id),
            func.count(InspectionImage.id).filter(has_reported_defect),
        )
        .select_from(Batch)
        .join(Board, Board.batch_id == Batch.id)
        .join(InspectionImage, InspectionImage.board_id == Board.id)
        .where(
            InspectionImage.status == ImageStatus.COMPLETED, InspectionImage.created_at >= since
        )
        .group_by(Batch.id, Batch.batch_number)
    )
    rows = (await db.execute(stmt)).all()
    return [
        (batch_id, batch_number, defect_count / total, total)
        for batch_id, batch_number, total, defect_count in rows
    ]


async def _window_defect_rate(db: AsyncSession, *, since: datetime) -> tuple[float, int]:
    has_reported_defect = exists(
        select(1).where(Detection.image_id == InspectionImage.id, Detection.is_reported.is_(True))
    )
    conditions = [
        InspectionImage.status == ImageStatus.COMPLETED,
        InspectionImage.created_at >= since,
    ]
    total = (
        await db.execute(select(func.count(InspectionImage.id)).where(*conditions))
    ).scalar() or 0
    if total == 0:
        return 0.0, 0
    defect_count = (
        await db.execute(
            select(func.count(InspectionImage.id)).where(*conditions, has_reported_defect)
        )
    ).scalar() or 0
    return defect_count / total, total


async def _latest_alert(
    db: AsyncSession, *, type_: QualityAlertType, scope_key: str
) -> QualityAlert | None:
    stmt = (
        select(QualityAlert)
        .where(QualityAlert.type == type_, QualityAlert.scope_key == scope_key)
        .order_by(QualityAlert.created_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _evaluate_scope(
    db: AsyncSession,
    *,
    type_: QualityAlertType,
    scope_key: str,
    observed_rate: float,
    threshold: float,
    context_extra: dict[str, Any],
) -> QualityAlert | None:
    """Applies the re-arm rule (acceptance criterion "No Alert Storm") and returns a newly
    created alert, or `None` if nothing changed.

    - A scope with an active (unacknowledged) alert is left alone — never a duplicate per poll.
    - A scope that's acknowledged but still over threshold stays quiet until it's observed back
      under threshold at least once (`cleared_at` records that); only then can it re-fire.
    - Anything else over threshold with no reason to stay quiet gets a fresh alert.
    """
    latest = await _latest_alert(db, type_=type_, scope_key=scope_key)
    over_threshold = observed_rate > threshold

    if latest is not None and latest.acknowledged_at is None:
        return None

    if latest is not None and latest.cleared_at is None:
        if not over_threshold:
            latest.cleared_at = datetime.now(UTC)
            await db.flush()
        return None

    if not over_threshold:
        return None

    alert = QualityAlert(
        type=type_,
        scope_key=scope_key,
        context={"observed_rate": observed_rate, "threshold": threshold, **context_extra},
    )
    db.add(alert)
    await db.flush()
    return alert


async def evaluate_thresholds(db: AsyncSession) -> list[QualityAlert]:
    """Computes the defect rate per batch and per configured time window, compares against
    FR-13's `alert_defect_rate_threshold`, and raises/re-arms `QualityAlert` rows accordingly
    (FR-19). Returns every alert newly created this poll so the caller (the Celery task) can
    emit one `alert.defect_rate` SSE event per new alert.
    """
    threshold = float(await get_config_value(db, "alert_defect_rate_threshold", default=0.15))
    window_minutes = int(await get_config_value(db, "alert_window_minutes", default=60))
    since = datetime.now(UTC) - timedelta(minutes=window_minutes)

    new_alerts: list[QualityAlert] = []

    for batch_id, batch_number, rate, total in await _batch_defect_rates(db, since=since):
        alert = await _evaluate_scope(
            db,
            type_=QualityAlertType.DEFECT_RATE_BATCH,
            scope_key=str(batch_id),
            observed_rate=rate,
            threshold=threshold,
            context_extra={
                "batch_id": str(batch_id),
                "batch_number": batch_number,
                "sample_size": total,
            },
        )
        if alert is not None:
            new_alerts.append(alert)

    window_rate, window_total = await _window_defect_rate(db, since=since)
    if window_total > 0:
        alert = await _evaluate_scope(
            db,
            type_=QualityAlertType.DEFECT_RATE_WINDOW,
            scope_key=_GLOBAL_WINDOW_SCOPE_KEY,
            observed_rate=window_rate,
            threshold=threshold,
            context_extra={"window_minutes": window_minutes, "sample_size": window_total},
        )
        if alert is not None:
            new_alerts.append(alert)

    await db.commit()
    for alert in new_alerts:
        await db.refresh(alert)
    return new_alerts


async def list_alerts(
    db: AsyncSession, *, acknowledged: bool | None, page: int, page_size: int
) -> tuple[int, list[QualityAlert]]:
    conditions = []
    if acknowledged is True:
        conditions.append(QualityAlert.acknowledged_at.is_not(None))
    elif acknowledged is False:
        conditions.append(QualityAlert.acknowledged_at.is_(None))

    count = (await db.execute(select(func.count(QualityAlert.id)).where(*conditions))).scalar() or 0
    rows = (
        (
            await db.execute(
                select(QualityAlert)
                .where(*conditions)
                .order_by(QualityAlert.created_at.desc(), QualityAlert.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return count, list(rows)


async def get_alert(db: AsyncSession, alert_id: uuid.UUID) -> QualityAlert | None:
    return await db.get(QualityAlert, alert_id)


async def acknowledge_alert(
    db: AsyncSession, *, actor_id: uuid.UUID, alert_id: uuid.UUID
) -> QualityAlert:
    alert = await get_alert(db, alert_id)
    if alert is None:
        raise ApiError("RESOURCE_NOT_FOUND", "Quality alert not found.", 404)
    if alert.acknowledged_at is not None:
        raise ApiError(
            "ALERT_ALREADY_ACKNOWLEDGED", "This alert has already been acknowledged.", 409
        )

    alert.acknowledged_by = actor_id
    alert.acknowledged_at = datetime.now(UTC)
    await db.flush()

    await record_audit(
        db,
        actor_id=actor_id,
        action="alert.acknowledged",
        entity_type="quality_alert",
        entity_id=alert.id,
        payload={"type": alert.type.value, "scope_key": alert.scope_key},
    )
    await db.commit()
    await db.refresh(alert)
    return alert
