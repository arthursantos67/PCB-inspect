"""Retention policy purge (FR-17, RN-08) — deletes `InspectionImage`/`Detection`/`Analysis`,
`Report` (Issue 20), and `DatasetExport` (Issue 21) rows once they're strictly past their
configured retention window, along with their derived files (annotated image, report file,
export ZIP). Original camera-captured files under the watch root, and every other row in the
database (including `AuditLog` itself, RN-08), are never touched.

`preview_purge` and `execute_purge` share the same cutoff/query logic so a dry-run can never
drift from what a real run would actually delete — the only difference is whether rows are
deleted and files removed.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.core.config import get_settings
from app.models import Analysis, ChatSession, DatasetExport, Detection, InspectionImage, Report
from app.settings.service import get_config_value

logger = logging.getLogger(__name__)

# RN-08 — minimum 2-year retention for inspections, detections, and analyses.
DEFAULT_RETENTION_DAYS = 730


@dataclass
class PurgeSummary:
    cutoffs: dict[str, str]
    counts: dict[str, int] = field(default_factory=dict)


async def _retention_days(db: AsyncSession, *, override_key: str | None = None) -> int:
    base = int(await get_config_value(db, "retention_days", default=DEFAULT_RETENTION_DAYS))
    if override_key is None:
        return base
    override = await get_config_value(db, override_key)
    return int(override) if override is not None else base


async def _watch_root(db: AsyncSession) -> Path:
    """The operator-configured watch root (`watch_root_path`, FR-13/FR-03) — falling back to the
    env-configured default (`app.core.config.Settings.watch_root`) if never overridden, same
    convention as `reports_output_dir` in `app.tasks.reports`/`app.tasks.dataset_exports`.
    """
    configured = await get_config_value(
        db, "watch_root_path", default=str(get_settings().watch_root)
    )
    return Path(configured).resolve()


async def _cutoffs(db: AsyncSession) -> dict[str, datetime]:
    now = datetime.now(UTC)
    inspections_days = await _retention_days(db)
    reports_days = await _retention_days(db, override_key="retention_days_reports")
    exports_days = await _retention_days(db, override_key="retention_days_exports")
    return {
        "inspections": now - timedelta(days=inspections_days),
        "reports": now - timedelta(days=reports_days),
        "exports": now - timedelta(days=exports_days),
    }


def _remove_derived_file(path_str: str | None, *, watch_root: Path) -> int:
    """Removes a derived file (annotated image / report / export ZIP) from disk. Returns 1 if a
    file was actually removed, 0 otherwise (already missing, no path recorded, or — as a defensive
    safety net, since this should never be reachable by construction — the path resolves under
    the watch root).
    """
    if not path_str:
        return 0
    path = Path(path_str)
    resolved = path.resolve()
    if resolved == watch_root or resolved.is_relative_to(watch_root):
        logger.error(
            "Refusing to remove a derived-file path that resolves under the watch root: %s",
            resolved,
        )
        return 0
    try:
        resolved.unlink()
    except FileNotFoundError:
        return 0
    return 1


async def _expired_inspection_images(
    db: AsyncSession, cutoff: datetime
) -> list[InspectionImage]:
    result = await db.scalars(select(InspectionImage).where(InspectionImage.created_at < cutoff))
    return list(result)


async def _expired_reports(db: AsyncSession, cutoff: datetime) -> list[Report]:
    result = await db.scalars(select(Report).where(Report.created_at < cutoff))
    return list(result)


async def _expired_dataset_exports(db: AsyncSession, cutoff: datetime) -> list[DatasetExport]:
    result = await db.scalars(select(DatasetExport).where(DatasetExport.created_at < cutoff))
    return list(result)


async def _counts_for_images(
    db: AsyncSession, image_ids: list[uuid.UUID]
) -> tuple[int, list[Analysis]]:
    """Detections cascade automatically on `InspectionImage` delete (DB-level `ondelete`), but
    `Analysis` doesn't (RN-03 wants reprocessing history preserved by default) — so it's counted
    here and returned for the caller to delete explicitly, after detaching any `ChatSession`
    still pointed at it.
    """
    if not image_ids:
        return 0, []
    detection_count = (
        await db.execute(
            select(func.count(Detection.id)).where(Detection.image_id.in_(image_ids))
        )
    ).scalar() or 0
    analyses = list(
        await db.scalars(select(Analysis).where(Analysis.image_id.in_(image_ids)))
    )
    return detection_count, analyses


def _build_summary(
    cutoffs: dict[str, datetime],
    *,
    image_count: int,
    detection_count: int,
    analysis_count: int,
    report_count: int,
    export_count: int,
    files_removed: int | None = None,
) -> PurgeSummary:
    counts = {
        "inspection_images": image_count,
        "detections": detection_count,
        "analyses": analysis_count,
        "reports": report_count,
        "dataset_exports": export_count,
    }
    if files_removed is not None:
        counts["files_removed"] = files_removed
    return PurgeSummary(cutoffs={k: v.isoformat() for k, v in cutoffs.items()}, counts=counts)


async def preview_purge(db: AsyncSession) -> PurgeSummary:
    """Read-only: what `execute_purge` would delete right now, given the current retention
    config — never deletes anything (AC "Dry-Run Available").
    """
    cutoffs = await _cutoffs(db)
    images = await _expired_inspection_images(db, cutoffs["inspections"])
    reports = await _expired_reports(db, cutoffs["reports"])
    exports = await _expired_dataset_exports(db, cutoffs["exports"])
    detection_count, analyses = await _counts_for_images(db, [image.id for image in images])

    return _build_summary(
        cutoffs,
        image_count=len(images),
        detection_count=detection_count,
        analysis_count=len(analyses),
        report_count=len(reports),
        export_count=len(exports),
    )


async def execute_purge(db: AsyncSession) -> PurgeSummary:
    """Deletes every record strictly past its configured retention window (AC "Correct Cutoff")
    and the derived files that go with it (AC "Derived Files Cleaned Up"), then stages one
    `AuditLog` row summarizing the run by entity-type counts (AC "Audited"). Running this twice
    in a row with nothing newly expired finds nothing to delete both times — a safe no-op
    (AC "Idempotent").
    """
    watch_root = await _watch_root(db)

    cutoffs = await _cutoffs(db)
    images = await _expired_inspection_images(db, cutoffs["inspections"])
    reports = await _expired_reports(db, cutoffs["reports"])
    exports = await _expired_dataset_exports(db, cutoffs["exports"])
    detection_count, analyses = await _counts_for_images(db, [image.id for image in images])

    files_removed = 0

    if analyses:
        # `ChatSession.context_analysis_id` has no `ondelete` (it's an optional context pointer,
        # not an ownership relationship) — detach it before deleting the `Analysis` row it
        # points to, or the delete would fail the FK constraint.
        analysis_ids = [analysis.id for analysis in analyses]
        await db.execute(
            update(ChatSession)
            .where(ChatSession.context_analysis_id.in_(analysis_ids))
            .values(context_analysis_id=None)
        )
        for analysis in analyses:
            await db.delete(analysis)

    for image in images:
        # `original_path` (the camera-captured file under the watch root, section 3.5) is never
        # touched — only the derived annotated image. `Detection`/`BoardDisposition` cascade at
        # the DB level once this row is gone.
        files_removed += _remove_derived_file(image.annotated_path, watch_root=watch_root)
        await db.delete(image)

    for report in reports:
        files_removed += _remove_derived_file(report.file_path, watch_root=watch_root)
        await db.delete(report)

    for export in exports:
        files_removed += _remove_derived_file(export.file_path, watch_root=watch_root)
        await db.delete(export)

    summary = _build_summary(
        cutoffs,
        image_count=len(images),
        detection_count=detection_count,
        analysis_count=len(analyses),
        report_count=len(reports),
        export_count=len(exports),
        files_removed=files_removed,
    )

    # System-initiated (no operator actor), same convention as `app.tasks.models`'s golden-set
    # evaluation audit entries.
    await record_audit(
        db,
        actor_id=None,
        action="retention.purged",
        entity_type="retention",
        payload={"cutoffs": summary.cutoffs, "counts": summary.counts},
    )
    await db.commit()
    return summary
