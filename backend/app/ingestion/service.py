"""Core ingestion logic (FR-03): one-off/watch-mode directory scanning and ad hoc import.

Both the `/scan` and `/import` endpoints return a batch summary with a per-file outcome
(`ingested` | `duplicate` | `failed` | `skipped`) rather than aborting on the first bad file —
this mirrors how watch mode must behave (one corrupted file can't stop the rest of a batch,
per the "Invalid File Handling" acceptance criterion) and keeps both endpoints consistent.
"""

import os
import uuid
from collections import Counter
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.ingestion.naming import infer_batch_and_board, iter_batch_files
from app.ingestion.schemas import (
    FileResult,
    ImportSummary,
    IngestionStatus,
    ScanSummary,
    WatchStatus,
)
from app.ingestion.validation import (
    InvalidImageError,
    read_image_metadata,
    sha256_checksum,
    sha256_checksum_bytes,
)
from app.models import Batch, Board, InspectionImage
from app.models.enums import ImageSource, ImageStatus
from app.tasks.pipeline import run_inference

DEFAULT_IMPORT_MAX_SIZE_MB = 25


async def validate_directory_path(path: Path) -> None:
    if not path.exists():
        raise ApiError("PATH_NOT_FOUND", f"Path does not exist: {path}", 422)
    if not path.is_dir():
        raise ApiError("PATH_NOT_FOUND", f"Path is not a directory: {path}", 422)
    if not os.access(path, os.R_OK | os.X_OK):
        raise ApiError("PATH_NOT_READABLE", f"Path is not readable: {path}", 422)


async def _get_or_create_batch(db: AsyncSession, batch_number: str) -> Batch:
    batch = await db.scalar(select(Batch).where(Batch.batch_number == batch_number))
    if batch is None:
        batch = Batch(batch_number=batch_number)
        db.add(batch)
        await db.flush()
    return batch


async def _get_or_create_board(db: AsyncSession, batch_id: uuid.UUID, board_number: str) -> Board:
    board = await db.scalar(
        select(Board).where(Board.batch_id == batch_id, Board.board_number == board_number)
    )
    if board is None:
        board = Board(batch_id=batch_id, board_number=board_number)
        db.add(board)
        await db.flush()
    return board


async def _is_known_path(db: AsyncSession, original_path: str) -> bool:
    existing = await db.scalar(
        select(InspectionImage.id).where(InspectionImage.original_path == original_path)
    )
    return existing is not None


async def _find_duplicate_in_batch(
    db: AsyncSession, batch_id: uuid.UUID, checksum: str
) -> uuid.UUID | None:
    result: uuid.UUID | None = await db.scalar(
        select(InspectionImage.id)
        .join(Board, InspectionImage.board_id == Board.id)
        .where(Board.batch_id == batch_id, InspectionImage.checksum_sha256 == checksum)
    )
    return result


async def _find_duplicate_import(db: AsyncSession, checksum: str) -> uuid.UUID | None:
    result: uuid.UUID | None = await db.scalar(
        select(InspectionImage.id).where(
            InspectionImage.board_id.is_(None),
            InspectionImage.source == ImageSource.MANUAL_IMPORT,
            InspectionImage.checksum_sha256 == checksum,
        )
    )
    return result


async def _ingest_batch_file(
    db: AsyncSession, *, root: Path, file_path: Path, source: ImageSource
) -> FileResult:
    original_path = str(file_path)
    if await _is_known_path(db, original_path):
        return FileResult(path=original_path, outcome="skipped", reason="already known")

    inferred = infer_batch_and_board(root, file_path)
    if inferred is None:
        return FileResult(
            path=original_path, outcome="skipped", reason="not under a batch subdirectory"
        )

    batch = await _get_or_create_batch(db, inferred.batch_number)
    checksum = sha256_checksum(file_path)

    try:
        meta = read_image_metadata(file_path)
    except InvalidImageError as exc:
        board = await _get_or_create_board(db, batch.id, inferred.board_number)
        image = InspectionImage(
            board_id=board.id,
            source=source,
            original_path=original_path,
            checksum_sha256=checksum,
            width=None,
            height=None,
            status=ImageStatus.FAILED,
            failure_reason=str(exc),
        )
        db.add(image)
        await db.flush()
        return FileResult(path=original_path, outcome="failed", image_id=image.id, reason=str(exc))

    duplicate_id = await _find_duplicate_in_batch(db, batch.id, checksum)
    if duplicate_id is not None:
        return FileResult(
            path=original_path,
            outcome="duplicate",
            image_id=duplicate_id,
            reason="checksum already ingested in this batch",
        )

    board = await _get_or_create_board(db, batch.id, inferred.board_number)
    image = InspectionImage(
        board_id=board.id,
        source=source,
        original_path=original_path,
        checksum_sha256=checksum,
        width=meta.width,
        height=meta.height,
        status=ImageStatus.QUEUED,
    )
    db.add(image)
    await db.flush()
    return FileResult(path=original_path, outcome="ingested", image_id=image.id)


def _enqueue_ingested(results: list[FileResult]) -> None:
    """Enqueues each newly-ingested image for inference (FR-04) only after its row has been
    committed — the worker runs in a separate process/connection and won't see an
    uncommitted row, so this must never run before `db.commit()`.
    """
    for result in results:
        if result.outcome == "ingested" and result.image_id is not None:
            run_inference.delay(str(result.image_id))


async def scan_directory(db: AsyncSession, path: Path, *, source: ImageSource) -> ScanSummary:
    """Shared by both the one-off `/scan` endpoint and each watch-mode poll (`source` differs
    only in which value is stamped on the resulting `InspectionImage.source`).
    """
    await validate_directory_path(path)

    files = iter_batch_files(path)
    results = [await _ingest_batch_file(db, root=path, file_path=f, source=source) for f in files]
    await db.commit()
    _enqueue_ingested(results)

    counts = Counter(r.outcome for r in results)
    return ScanSummary(
        path=str(path),
        discovered=len(files),
        ingested=counts["ingested"],
        duplicate=counts["duplicate"],
        failed=counts["failed"],
        skipped=counts["skipped"],
        files=results,
    )


async def get_import_max_size_mb(db: AsyncSession) -> float:
    from app.settings import service as settings_service

    value = await settings_service.get_config_value(
        db, "import_max_size_mb", DEFAULT_IMPORT_MAX_SIZE_MB
    )
    return float(value)


async def import_files(
    db: AsyncSession,
    *,
    uploads: list[UploadFile],
    created_by: uuid.UUID,
    max_size_bytes: int,
    app_data_dir: Path,
) -> ImportSummary:
    """Ad hoc import (secondary path, FR-03) — unlike scan/watch, this does copy bytes: the
    browser has no other way to hand the backend a file outside the watch root.
    """
    import_dir = app_data_dir / "imports"
    import_dir.mkdir(parents=True, exist_ok=True)

    results: list[FileResult] = []
    for upload in uploads:
        display_name = upload.filename or "upload"
        data = await upload.read()

        if len(data) > max_size_bytes:
            results.append(
                FileResult(path=display_name, outcome="failed", reason="FILE_TOO_LARGE")
            )
            continue

        checksum = sha256_checksum_bytes(data)
        duplicate_id = await _find_duplicate_import(db, checksum)
        if duplicate_id is not None:
            results.append(
                FileResult(
                    path=display_name,
                    outcome="duplicate",
                    image_id=duplicate_id,
                    reason="checksum already imported",
                )
            )
            continue

        dest = import_dir / f"{uuid.uuid4()}_{Path(display_name).name}"
        dest.write_bytes(data)

        try:
            meta = read_image_metadata(dest)
        except InvalidImageError as exc:
            image = InspectionImage(
                source=ImageSource.MANUAL_IMPORT,
                original_path=str(dest),
                checksum_sha256=checksum,
                width=None,
                height=None,
                status=ImageStatus.FAILED,
                failure_reason=str(exc),
                created_by=created_by,
            )
            db.add(image)
            await db.flush()
            results.append(
                FileResult(path=display_name, outcome="failed", image_id=image.id, reason=str(exc))
            )
            continue

        image = InspectionImage(
            source=ImageSource.MANUAL_IMPORT,
            original_path=str(dest),
            checksum_sha256=checksum,
            width=meta.width,
            height=meta.height,
            status=ImageStatus.QUEUED,
            created_by=created_by,
        )
        db.add(image)
        await db.flush()
        results.append(FileResult(path=display_name, outcome="ingested", image_id=image.id))

    await db.commit()
    _enqueue_ingested(results)

    counts = Counter(r.outcome for r in results)
    return ImportSummary(
        ingested=counts["ingested"],
        duplicate=counts["duplicate"],
        failed=counts["failed"],
        files=results,
    )


async def get_ingestion_status(db: AsyncSession) -> IngestionStatus:
    from app.settings import service as settings_service

    watch_root_path = await settings_service.get_config_value(db, "watch_root_path")
    watch_mode_enabled = bool(
        await settings_service.get_config_value(db, "watch_mode_enabled", True)
    )

    files_discovered = await db.scalar(
        select(func.count())
        .select_from(InspectionImage)
        .where(InspectionImage.source == ImageSource.WATCH_FOLDER)
    ) or 0
    files_failed = await db.scalar(
        select(func.count())
        .select_from(InspectionImage)
        .where(
            InspectionImage.source == ImageSource.WATCH_FOLDER,
            InspectionImage.status == ImageStatus.FAILED,
        )
    ) or 0
    files_ingested = files_discovered - files_failed

    status: WatchStatus
    detail: str | None = None
    if not watch_root_path:
        status = "not_configured"
    elif not watch_mode_enabled:
        status = "paused"
    else:
        try:
            await validate_directory_path(Path(str(watch_root_path)))
            status = "watching"
        except ApiError as exc:
            status = "error"
            detail = exc.message

    return IngestionStatus(
        status=status,
        watch_root_path=str(watch_root_path) if watch_root_path else None,
        watch_mode_enabled=watch_mode_enabled,
        files_discovered=files_discovered,
        files_ingested=files_ingested,
        files_failed=files_failed,
        detail=detail,
    )
