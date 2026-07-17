"""Report generation task (FR-11, Issue 35) — the real path. Runs `generate_report` via
`.apply()` (eager execution, no Redis broker in the test environment) directly against
`task_db_session()`, same convention as `test_model_evaluation_task.py`.
"""

import asyncio
import uuid
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import openpyxl
from sqlalchemy import text

from app.core.security import hash_password
from app.inspections.filters import InspectionFilters, apply_filters, base_query
from app.models import (
    Batch,
    Board,
    Detection,
    InspectionImage,
    ModelVersion,
    Report,
    SystemConfig,
    User,
)
from app.models.enums import (
    DefectType,
    ImageSource,
    ImageStatus,
    ReportFormat,
    ReportStatus,
    ReportType,
)
from app.tasks.db import task_db_session
from app.tasks.reports import generate_report

_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


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


async def _set_reports_output_dir(path: Path) -> None:
    async with task_db_session() as db:
        db.add(SystemConfig(key="reports_output_dir", value=str(path)))
        await db.commit()


async def _create_report(
    *,
    report_type: ReportType,
    report_format: ReportFormat,
    requested_by: uuid.UUID,
    filters: dict[str, Any] | None = None,
) -> uuid.UUID:
    async with task_db_session() as db:
        report = Report(
            type=report_type, format=report_format, filters=filters, requested_by=requested_by
        )
        db.add(report)
        await db.commit()
        return report.id


async def _get_report(report_id: uuid.UUID) -> Report | None:
    async with task_db_session() as db:
        return await db.get(Report, report_id)


async def _seed_inspections() -> dict[str, uuid.UUID]:
    """Two batches, mixed defect types/severity — enough to exercise a filter that matches a
    strict subset (batch_number=BATCH-A) as well as the "no filter, everything" case.
    """
    async with task_db_session() as db:
        model_version = ModelVersion(
            version=f"v-{uuid.uuid4().hex[:8]}", weights_path="/weights/best.pt", is_active=True
        )
        db.add(model_version)
        await db.flush()

        batch_a = Batch(batch_number="BATCH-A")
        batch_b = Batch(batch_number="BATCH-B")
        db.add_all([batch_a, batch_b])
        await db.flush()

        board_a1 = Board(batch_id=batch_a.id, board_number="A1")
        board_a2 = Board(batch_id=batch_a.id, board_number="A2")
        board_b1 = Board(batch_id=batch_b.id, board_number="B1")
        db.add_all([board_a1, board_a2, board_b1])
        await db.flush()

        image_ids = []
        for board, defect_type, offset in (
            (board_a1, DefectType.MOUSE_BITE, 3),
            (board_a2, DefectType.SHORT, 2),
            (board_b1, DefectType.SPUR, 1),
        ):
            image = InspectionImage(
                board_id=board.id,
                source=ImageSource.WATCH_FOLDER,
                original_path=f"/tmp/{uuid.uuid4()}.jpg",
                checksum_sha256=uuid.uuid4().hex,
                status=ImageStatus.COMPLETED,
                created_at=_NOW - timedelta(days=offset),
            )
            db.add(image)
            await db.flush()
            db.add(
                Detection(
                    image_id=image.id,
                    defect_type=defect_type,
                    bbox={"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4},
                    confidence=Decimal("0.900"),
                    is_reported=True,
                    model_version_id=model_version.id,
                )
            )
            image_ids.append(image.id)

        await db.commit()
        return {"image_a1": image_ids[0], "image_a2": image_ids[1], "image_b1": image_ids[2]}


_TABLES_IN_FK_ORDER = (
    "detection",
    "inspection_image",
    "board",
    "batch",
    "model_version",
    "report",
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


# --- Consolidated: filter parity with GET /api/v1/inspections (Issue 35 acceptance test) --


def test_consolidated_report_row_count_matches_inspections_filter(tmp_path: Path) -> None:
    _run(_set_reports_output_dir(tmp_path))
    _run(_seed_inspections())
    user_id = _run(_create_user())

    report_id = _run(
        _create_report(
            report_type=ReportType.CONSOLIDATED,
            report_format=ReportFormat.CSV,
            requested_by=user_id,
            filters={"batch_number": "BATCH-A"},
        )
    )

    generate_report.apply(args=[str(report_id)])

    report = _run(_get_report(report_id))
    assert report is not None
    assert report.status == ReportStatus.COMPLETED
    assert report.error_message is None
    assert report.file_path is not None
    assert Path(report.file_path).is_file()

    # The same filter, computed the same way `GET /api/v1/inspections?batch_number=BATCH-A`
    # would (`app.inspections.filters.apply_filters` + `base_query`) — this is what
    # guarantees the report can never silently drift from the search screen (Issue 8).
    async def _matching_count() -> int:
        async with task_db_session() as db:
            stmt = apply_filters(
                base_query(InspectionImage.id), InspectionFilters(batch_number="BATCH-A")
            )
            return len((await db.execute(stmt)).all())

    expected_count = _run(_matching_count())
    assert expected_count == 2  # board_a1 + board_a2, not board_b1
    assert report.row_count == expected_count


def test_consolidated_report_with_no_filters_includes_every_inspection(tmp_path: Path) -> None:
    _run(_set_reports_output_dir(tmp_path))
    _run(_seed_inspections())
    user_id = _run(_create_user())

    report_id = _run(
        _create_report(
            report_type=ReportType.CONSOLIDATED,
            report_format=ReportFormat.XLSX,
            requested_by=user_id,
            filters={},
        )
    )

    generate_report.apply(args=[str(report_id)])

    report = _run(_get_report(report_id))
    assert report is not None
    assert report.status == ReportStatus.COMPLETED
    assert report.row_count == 3

    workbook = openpyxl.load_workbook(report.file_path)
    sheet = workbook.active
    # Header row + 3 data rows.
    assert sheet.max_row == 4


def test_consolidated_report_pdf_format_produces_a_valid_file(tmp_path: Path) -> None:
    _run(_set_reports_output_dir(tmp_path))
    _run(_seed_inspections())
    user_id = _run(_create_user())

    report_id = _run(
        _create_report(
            report_type=ReportType.CONSOLIDATED,
            report_format=ReportFormat.PDF,
            requested_by=user_id,
            filters={},
        )
    )

    generate_report.apply(args=[str(report_id)])

    report = _run(_get_report(report_id))
    assert report is not None
    assert report.status == ReportStatus.COMPLETED
    assert Path(report.file_path).read_bytes().startswith(b"%PDF")


# --- Individual -----------------------------------------------------------------------------


def test_individual_report_produces_a_valid_pdf(tmp_path: Path) -> None:
    _run(_set_reports_output_dir(tmp_path))
    image_ids = _run(_seed_inspections())
    user_id = _run(_create_user())

    report_id = _run(
        _create_report(
            report_type=ReportType.INDIVIDUAL,
            report_format=ReportFormat.PDF,
            requested_by=user_id,
            filters={"inspection_id": str(image_ids["image_a1"])},
        )
    )

    generate_report.apply(args=[str(report_id)])

    report = _run(_get_report(report_id))
    assert report is not None
    assert report.status == ReportStatus.COMPLETED
    assert report.row_count == 1  # one detection on that inspection
    assert Path(report.file_path).read_bytes().startswith(b"%PDF")


def test_individual_report_with_unknown_inspection_fails_gracefully(tmp_path: Path) -> None:
    """A bad/stale inspection_id must degrade to a visible `FAILED` report, never crash the
    worker (mirrors `app.tasks.models`'s golden-set evaluation error handling).
    """
    _run(_set_reports_output_dir(tmp_path))
    user_id = _run(_create_user())

    report_id = _run(
        _create_report(
            report_type=ReportType.INDIVIDUAL,
            report_format=ReportFormat.PDF,
            requested_by=user_id,
            filters={"inspection_id": str(uuid.uuid4())},
        )
    )

    generate_report.apply(args=[str(report_id)])

    report = _run(_get_report(report_id))
    assert report is not None
    assert report.status == ReportStatus.FAILED
    assert report.error_message is not None
    assert report.file_path is None


# --- Executive -------------------------------------------------------------------------------


def test_executive_report_produces_a_valid_pdf(tmp_path: Path) -> None:
    _run(_set_reports_output_dir(tmp_path))
    _run(_seed_inspections())
    user_id = _run(_create_user())

    report_id = _run(
        _create_report(
            report_type=ReportType.EXECUTIVE,
            report_format=ReportFormat.PDF,
            requested_by=user_id,
            filters={},
        )
    )

    generate_report.apply(args=[str(report_id)])

    report = _run(_get_report(report_id))
    assert report is not None
    assert report.status == ReportStatus.COMPLETED
    assert Path(report.file_path).read_bytes().startswith(b"%PDF")
