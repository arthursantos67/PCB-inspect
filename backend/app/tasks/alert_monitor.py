"""Quality alert monitoring (FR-19) — the housekeeping-queue beat task (`app.tasks.celery_app`,
every 5 minutes) that evaluates defect-rate thresholds and raises/re-arms `QualityAlert` rows.
The evaluation and re-arm logic itself lives in `app.alerts.service.evaluate_thresholds`, shared
with nothing else (there's no other caller) but kept out of this module so it can be exercised
directly in tests without going through Celery.

Drives its own throwaway `asyncio.run()` loop, same as every other Celery task in this codebase
(see `app.tasks.db.task_db_session`'s module docstring).
"""

import asyncio

from app.alerts.service import evaluate_thresholds as _evaluate_thresholds
from app.events.publisher import publish_event
from app.tasks.celery_app import celery_app
from app.tasks.db import task_db_session


@celery_app.task(name="app.tasks.alert_monitor.evaluate_thresholds")
def evaluate_thresholds() -> None:
    asyncio.run(_evaluate_thresholds_async())


async def _evaluate_thresholds_async() -> None:
    async with task_db_session() as db:
        new_alerts = await _evaluate_thresholds(db)

    for alert in new_alerts:
        await publish_event(
            "alert.defect_rate",
            {
                "id": str(alert.id),
                "type": alert.type.value,
                "scope_key": alert.scope_key,
                "context": alert.context,
            },
        )
