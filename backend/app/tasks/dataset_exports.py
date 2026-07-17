"""Dataset export generation (FR-18) — dispatches to `app.datasets.exporter`, which assembles a
labeled YOLO-format package from reviewed detections (Issue 33) and traces back to the model
version(s) that produced them (RV-05). Routed to the `housekeeping` queue (`app.tasks.celery_app`)
for the same reason as report generation (`app.tasks.reports`): it must survive a dead/
misconfigured agents or inference worker.

Drives its own throwaway `asyncio.run()` loop, same as every other Celery task in this codebase
(see `app.tasks.db.task_db_session`'s module docstring).
"""

import asyncio
import logging
import uuid
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import ApiError
from app.datasets.exporter import generate
from app.events.publisher import publish_event
from app.models import DatasetExport
from app.models.enums import DatasetExportStatus
from app.settings.service import get_config_value
from app.tasks.celery_app import celery_app
from app.tasks.db import task_db_session

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.dataset_exports.generate_dataset_export")
def generate_dataset_export(export_id: str) -> None:
    """Enqueued right after a `DatasetExport` row is created (`app.datasets.router`)."""
    asyncio.run(_generate_dataset_export_async(export_id))


async def _generate_dataset_export_async(export_id: str) -> None:
    export_uuid = uuid.UUID(export_id)

    async with task_db_session() as db:
        export = await db.get(DatasetExport, export_uuid)
        if export is None:
            return

        try:
            # Shared with report generation (FR-11/FR-18, see config_schema.py) — one operator-
            # configured "reports/exports output directory" (FR-13) for both.
            output_dir = Path(
                await get_config_value(
                    db,
                    "reports_output_dir",
                    default=str(get_settings().app_data_dir / "reports"),
                )
            )
            result = await generate(db, export, output_dir)
        except Exception as exc:  # noqa: BLE001 — a bad filter or missing source image must
            # degrade to a FAILED export the operator can see, never crash the worker (mirrors
            # app.tasks.reports's error handling).
            reason = exc.message if isinstance(exc, ApiError) else str(exc)
            logger.warning(
                "Dataset export generation failed for export_id=%s: %s",
                export_id,
                reason,
                exc_info=True,
            )
            export.status = DatasetExportStatus.FAILED
            export.error_message = reason
            await db.commit()
            await publish_event("dataset_export.failed", {"id": export_id, "status": "FAILED"})
            return

        export.status = DatasetExportStatus.COMPLETED
        export.file_path = str(result.file_path)
        export.manifest = result.manifest
        await db.commit()

    await publish_event("dataset_export.completed", {"id": export_id, "status": "COMPLETED"})
