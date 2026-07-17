"""Retention purge (FR-17, Issue 39). Runs `app.retention.service` directly against
`task_db_session()`, and `purge_expired` via `.apply()` (eager execution, no Redis broker in the
test environment) for the Celery wiring itself — same convention as `test_report_generation.py`/
`test_alert_monitoring.py`.

Acceptance criteria covered:
- Correct Cutoff: only records strictly past the configured retention window are purged.
- Watch Root Untouched: a derived-file path that resolves under the configured watch root is
  never removed, even if it were (mis)recorded as such.
- Derived Files Cleaned Up: purging a row also removes its annotated image / report file /
  export ZIP from disk.
- Audited: each purge run produces one `AuditLog` row summarizing counts per entity type.
- Dry-Run Available: `preview_purge` (and its API route) reports what would be purged without
  deleting anything.
- Idempotent: a second run with nothing newly expired is a safe no-op.
"""

import asyncio
import uuid
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import (
    Analysis,
    AuditLog,
    ChatSession,
    DatasetExport,
    Detection,
    InspectionImage,
    Report,
    SystemConfig,
    User,
)
from app.models.enums import (
    AnalysisSource,
    AnalysisStatus,
    DatasetExportStatus,
    DefectType,
    ImageSource,
    ImageStatus,
    ReportFormat,
    ReportStatus,
    ReportType,
)
from app.retention.service import execute_purge, preview_purge
from app.tasks.db import task_db_session
from app.tasks.retention import purge_expired


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _days_ago(days: int) -> datetime:
    """Purge cutoffs are computed against the real wall clock (`datetime.now(UTC)`), so test
    fixtures must be relative to it too, not a fixed reference date.
    """
    return datetime.now(UTC) - timedelta(days=days)


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


async def _set_config(**values: Any) -> None:
    async with task_db_session() as db:
        for key, value in values.items():
            db.add(SystemConfig(key=key, value=value))
        await db.commit()


async def _create_image(
    *, created_at: datetime, annotated_path: str | None, with_analysis: bool = False
) -> uuid.UUID:
    async with task_db_session() as db:
        image = InspectionImage(
            source=ImageSource.WATCH_FOLDER,
            original_path=f"/data/watch-root/{uuid.uuid4()}.jpg",
            annotated_path=annotated_path,
            checksum_sha256=uuid.uuid4().hex,
            status=ImageStatus.COMPLETED,
            created_at=created_at,
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
        if with_analysis:
            db.add(
                Analysis(
                    image_id=image.id,
                    status=AnalysisStatus.COMPLETED,
                    source=AnalysisSource.KNOWLEDGE_BASE,
                )
            )
        await db.commit()
        return image.id


async def _create_report(
    *, created_at: datetime, file_path: str | None, requested_by: uuid.UUID
) -> uuid.UUID:
    async with task_db_session() as db:
        report = Report(
            type=ReportType.INDIVIDUAL,
            format=ReportFormat.PDF,
            status=ReportStatus.COMPLETED,
            file_path=file_path,
            requested_by=requested_by,
            created_at=created_at,
        )
        db.add(report)
        await db.commit()
        return report.id


async def _create_dataset_export(
    *, created_at: datetime, file_path: str | None, requested_by: uuid.UUID
) -> uuid.UUID:
    async with task_db_session() as db:
        export = DatasetExport(
            status=DatasetExportStatus.COMPLETED,
            file_path=file_path,
            requested_by=requested_by,
            created_at=created_at,
        )
        db.add(export)
        await db.commit()
        return export.id


async def _get(model: type, row_id: Any) -> Any:
    async with task_db_session() as db:
        return await db.get(model, row_id)


async def _count(model: type) -> int:
    async with task_db_session() as db:
        return len(list(await db.scalars(select(model))))


_TABLES_IN_FK_ORDER = (
    "chat_message",
    "chat_session",
    "analysis_review",
    "board_disposition",
    "detection",
    "analysis",
    "inspection_image",
    "audit_log",
    "report",
    "dataset_export",
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


# --- Correct cutoff / derived files ----------------------------------------------------------


def test_purge_deletes_only_expired_inspection_images_and_their_derived_files(
    tmp_path: Path,
) -> None:
    expired_annotated = tmp_path / "expired-annotated.png"
    expired_annotated.write_bytes(b"expired")
    fresh_annotated = tmp_path / "fresh-annotated.png"
    fresh_annotated.write_bytes(b"fresh")

    expired_id = _run(
        _create_image(
            created_at=_days_ago(731),
            annotated_path=str(expired_annotated),
            with_analysis=True,
        )
    )
    fresh_id = _run(
        _create_image(
            created_at=_days_ago(1),
            annotated_path=str(fresh_annotated),
            with_analysis=True,
        )
    )

    summary = _run(_run_execute_purge())

    assert summary.counts["inspection_images"] == 1
    assert summary.counts["detections"] == 1
    assert summary.counts["analyses"] == 1
    assert _run(_get(InspectionImage, expired_id)) is None
    assert not expired_annotated.exists()

    assert _run(_get(InspectionImage, fresh_id)) is not None
    assert fresh_annotated.exists()
    assert _run(_count(Detection)) == 1
    assert _run(_count(Analysis)) == 1


async def _run_execute_purge() -> Any:
    async with task_db_session() as db:
        return await execute_purge(db)


def test_purge_detaches_chat_sessions_before_deleting_their_analysis(tmp_path: Path) -> None:
    """`ChatSession.context_analysis_id` has no `ondelete` — deleting an expired `Analysis` a
    session still points to must null that reference out first, not fail the delete.
    """
    expired_id = _run(
        _create_image(created_at=_days_ago(800), annotated_path=None, with_analysis=True)
    )

    async def _seed_chat_session() -> uuid.UUID:
        async with task_db_session() as db:
            image = await db.get(InspectionImage, expired_id)
            assert image is not None
            analysis = (
                await db.scalars(select(Analysis).where(Analysis.image_id == expired_id))
            ).one()
            user = User(
                email=f"{uuid.uuid4()}@pcb-inspect.local",
                password_hash=hash_password("correct-horse-battery"),
                full_name="Operator",
            )
            db.add(user)
            await db.flush()
            session = ChatSession(user_id=user.id, context_analysis_id=analysis.id)
            db.add(session)
            await db.commit()
            return session.id

    session_id = _run(_seed_chat_session())

    _run(_run_execute_purge())

    session = _run(_get(ChatSession, session_id))
    assert session is not None
    assert session.context_analysis_id is None


def test_purge_removes_expired_reports_and_dataset_exports(tmp_path: Path) -> None:
    user_id = _run(_create_user())

    expired_report_file = tmp_path / "expired-report.pdf"
    expired_report_file.write_bytes(b"pdf")
    fresh_report_file = tmp_path / "fresh-report.pdf"
    fresh_report_file.write_bytes(b"pdf")

    expired_export_file = tmp_path / "expired-export.zip"
    expired_export_file.write_bytes(b"zip")
    fresh_export_file = tmp_path / "fresh-export.zip"
    fresh_export_file.write_bytes(b"zip")

    expired_report_id = _run(
        _create_report(
            created_at=_days_ago(731),
            file_path=str(expired_report_file),
            requested_by=user_id,
        )
    )
    fresh_report_id = _run(
        _create_report(
            created_at=_days_ago(1), file_path=str(fresh_report_file), requested_by=user_id
        )
    )
    expired_export_id = _run(
        _create_dataset_export(
            created_at=_days_ago(731),
            file_path=str(expired_export_file),
            requested_by=user_id,
        )
    )
    fresh_export_id = _run(
        _create_dataset_export(
            created_at=_days_ago(1), file_path=str(fresh_export_file), requested_by=user_id
        )
    )

    summary = _run(_run_execute_purge())

    assert summary.counts["reports"] == 1
    assert summary.counts["dataset_exports"] == 1
    assert _run(_get(Report, expired_report_id)) is None
    assert not expired_report_file.exists()
    assert _run(_get(Report, fresh_report_id)) is not None
    assert fresh_report_file.exists()

    assert _run(_get(DatasetExport, expired_export_id)) is None
    assert not expired_export_file.exists()
    assert _run(_get(DatasetExport, fresh_export_id)) is not None
    assert fresh_export_file.exists()


def test_report_retention_override_is_shorter_than_base_inspection_retention(
    tmp_path: Path,
) -> None:
    """A per-artifact override (`retention_days_reports`) can purge a `Report` well before the
    base `retention_days` window that still protects inspection data of the same age.
    """
    user_id = _run(_create_user())
    _run(_set_config(retention_days=730, retention_days_reports=5))

    report_file = tmp_path / "report.pdf"
    report_file.write_bytes(b"pdf")
    report_id = _run(
        _create_report(
            created_at=_days_ago(10), file_path=str(report_file), requested_by=user_id
        )
    )
    image_id = _run(
        _create_image(created_at=_days_ago(10), annotated_path=None)
    )

    summary = _run(_run_execute_purge())

    assert summary.counts["reports"] == 1
    assert summary.counts["inspection_images"] == 0
    assert _run(_get(Report, report_id)) is None
    assert not report_file.exists()
    assert _run(_get(InspectionImage, image_id)) is not None


# --- Watch root untouched ----------------------------------------------------------------------


def test_purge_never_removes_a_file_under_the_watch_root(tmp_path: Path) -> None:
    watch_root = tmp_path / "watch-root"
    watch_root.mkdir()
    camera_file = watch_root / "board.jpg"
    camera_file.write_bytes(b"camera-captured, never touched")

    _run(_set_config(watch_root_path=str(watch_root)))

    # Simulated bad data: an `annotated_path` that (incorrectly) resolves under the watch root.
    # Even then, the safety net must refuse to remove it.
    image_id = _run(
        _create_image(created_at=_days_ago(731), annotated_path=str(camera_file))
    )

    _run(_run_execute_purge())

    assert camera_file.exists()
    assert camera_file.read_bytes() == b"camera-captured, never touched"
    assert _run(_get(InspectionImage, image_id)) is None


# --- Audited -------------------------------------------------------------------------------


def test_purge_produces_one_audit_log_entry_summarizing_counts(tmp_path: Path) -> None:
    _run(_create_image(created_at=_days_ago(731), annotated_path=None))
    _run(_create_image(created_at=_days_ago(1), annotated_path=None))

    _run(_run_execute_purge())

    async def _audit_entries() -> list[AuditLog]:
        async with task_db_session() as db:
            return list(
                await db.scalars(select(AuditLog).where(AuditLog.action == "retention.purged"))
            )

    entries = _run(_audit_entries())
    assert len(entries) == 1
    entry = entries[0]
    assert entry.entity_type == "retention"
    assert entry.payload is not None
    assert entry.payload["counts"]["inspection_images"] == 1


# --- Dry-run ---------------------------------------------------------------------------------


def test_preview_purge_reports_counts_without_deleting_anything(tmp_path: Path) -> None:
    annotated = tmp_path / "annotated.png"
    annotated.write_bytes(b"data")
    image_id = _run(
        _create_image(created_at=_days_ago(731), annotated_path=str(annotated))
    )

    async def _preview() -> Any:
        async with task_db_session() as db:
            return await preview_purge(db)

    summary = _run(_preview())

    assert summary.counts["inspection_images"] == 1
    assert "files_removed" not in summary.counts
    assert _run(_get(InspectionImage, image_id)) is not None
    assert annotated.exists()

    async def _no_audit_entries() -> int:
        async with task_db_session() as db:
            return len(list(await db.scalars(select(AuditLog))))

    assert _run(_no_audit_entries()) == 0


async def test_retention_preview_endpoint_is_read_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    setup_response = await client.post(
        "/api/v1/auth/setup",
        json={
            "email": "operator@pcb-inspect.local",
            "password": "correct-horse-battery",
            "full_name": "Operator",
        },
    )
    token = setup_response.json()["access_token"]

    db_session.add(
        InspectionImage(
            source=ImageSource.WATCH_FOLDER,
            original_path=f"/data/watch-root/{uuid.uuid4()}.jpg",
            checksum_sha256=uuid.uuid4().hex,
            status=ImageStatus.COMPLETED,
            created_at=_days_ago(731),
        )
    )
    await db_session.commit()

    response = await client.get(
        "/api/v1/retention/preview", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["inspection_images"] == 1
    assert "inspections" in body["cutoffs"]
    # Still there — a preview never deletes.
    remaining = await db_session.scalars(select(InspectionImage))
    assert len(list(remaining)) == 1


# --- Idempotent --------------------------------------------------------------------------------


def test_running_purge_twice_with_nothing_newly_expired_is_a_safe_no_op(tmp_path: Path) -> None:
    annotated = tmp_path / "annotated.png"
    annotated.write_bytes(b"data")
    _run(_create_image(created_at=_days_ago(731), annotated_path=str(annotated)))

    first = _run(_run_execute_purge())
    assert first.counts["inspection_images"] == 1

    second = _run(_run_execute_purge())
    assert second.counts["inspection_images"] == 0
    assert second.counts["detections"] == 0
    assert second.counts["analyses"] == 0
    assert second.counts["reports"] == 0
    assert second.counts["dataset_exports"] == 0
    assert second.counts["files_removed"] == 0


# --- Celery task wiring ------------------------------------------------------------------------


def test_purge_expired_task_runs_the_real_purge_logic() -> None:
    image_id = _run(_create_image(created_at=_days_ago(731), annotated_path=None))

    purge_expired.apply()

    assert _run(_get(InspectionImage, image_id)) is None
