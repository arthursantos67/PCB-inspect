"""Retention purge (FR-17) — the housekeeping-queue beat task (`app.tasks.celery_app`, once a
day) that deletes `InspectionImage`/`Detection`/`Analysis`, `Report`, and `DatasetExport` rows
past their configured retention window, and the derived files that go with them. The actual
cutoff/query/delete/audit logic lives in `app.retention.service` — kept out of this module so it
can be exercised directly in tests without going through Celery, same convention as
`app.tasks.alert_monitor`.

Drives its own throwaway `asyncio.run()` loop, same as every other Celery task in this codebase
(see `app.tasks.db.task_db_session`'s module docstring).
"""

import asyncio

from app.retention.service import execute_purge
from app.tasks.celery_app import celery_app
from app.tasks.db import task_db_session


@celery_app.task(name="app.tasks.retention.purge_expired")
def purge_expired() -> None:
    asyncio.run(_purge_expired_async())


async def _purge_expired_async() -> None:
    async with task_db_session() as db:
        await execute_purge(db)
