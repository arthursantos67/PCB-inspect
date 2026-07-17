"""Report generation (FR-11) — dispatches by `Report.type`/`.format` to `app.reports.content`,
which in turn reuses `app.inspections.filters`/`.service` (Issue 8) for consolidated reports
and `app.stats.service` (Issue 9) for executive summaries. Routed to the `housekeeping` queue
(`app.tasks.celery_app`) — report generation must survive a dead/misconfigured agents or
inference worker, same rationale as ingestion polling/alerting/retention.

Drives its own throwaway `asyncio.run()` loop, same as every other Celery task in this codebase
(see `app.tasks.db.task_db_session`'s module docstring).
"""

import asyncio
import logging
import uuid
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import ApiError
from app.events.publisher import publish_event
from app.models import Report
from app.models.enums import ReportStatus
from app.reports.content import generate
from app.settings.service import get_config_value
from app.tasks.celery_app import celery_app
from app.tasks.db import task_db_session

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.reports.generate_report")
def generate_report(report_id: str) -> None:
    """Enqueued right after a `Report` row is created (`app.reports.router`)."""
    asyncio.run(_generate_report_async(report_id))


async def _generate_report_async(report_id: str) -> None:
    report_uuid = uuid.UUID(report_id)

    async with task_db_session() as db:
        report = await db.get(Report, report_uuid)
        if report is None:
            return

        try:
            output_dir = Path(
                await get_config_value(
                    db,
                    "reports_output_dir",
                    default=str(get_settings().app_data_dir / "reports"),
                )
            )
            result = await generate(db, report, output_dir)
        except Exception as exc:  # noqa: BLE001 — a bad filter/inspection id must degrade to a
            # FAILED report the operator can see, never crash the worker (mirrors
            # app.tasks.models's golden-set evaluation error handling).
            reason = exc.message if isinstance(exc, ApiError) else str(exc)
            logger.warning(
                "Report generation failed for report_id=%s: %s", report_id, reason, exc_info=True
            )
            report.status = ReportStatus.FAILED
            report.error_message = reason
            await db.commit()
            await publish_event("report.failed", {"id": report_id, "status": "FAILED"})
            return

        report.status = ReportStatus.COMPLETED
        report.file_path = str(result.file_path)
        report.row_count = result.row_count
        await db.commit()

    await publish_event("report.completed", {"id": report_id, "status": "COMPLETED"})
