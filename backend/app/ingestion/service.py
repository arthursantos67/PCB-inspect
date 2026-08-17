"""Core ingestion logic (FR-03): directory scanning, shared by watch mode and the one-off scan.

Images are always read in place from a directory the backend can reach on the operator's own
machine — nothing is ever uploaded, copied, moved, renamed, or deleted (section 3.5).

A scan returns a per-file outcome (`ingested` | `duplicate` | `failed` | `skipped`) rather than
aborting on the first bad file, because that is how watch mode must behave: one corrupted file
can't stop the rest of a batch, per the "Invalid File Handling" acceptance criterion.
"""

import asyncio
import logging
import os
import uuid
from collections import Counter
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.host_paths import to_container_path, to_host_path
from app.events.publisher import publish_event
from app.ingestion.naming import BatchBoard, infer_batch_and_board, iter_batch_files
from app.ingestion.schemas import FileResult, IngestionStatus, ScanSummary, WatchStatus
from app.ingestion.validation import InvalidImageError, read_image_metadata, sha256_checksum
from app.models import Batch, Board, InspectionImage
from app.models.enums import ImageSource, ImageStatus
from app.tasks.pipeline import run_inference

logger = logging.getLogger(__name__)


async def validate_directory_path(path: Path) -> None:
    """`path` is a host path as the operator entered it; the checks run against the container's
    view of it, but every message names the host path the operator would recognize.
    """
    resolved = to_container_path(path)
    if not resolved.exists():
        raise ApiError("PATH_NOT_FOUND", f"Path does not exist: {path}", 422)
    if not resolved.is_dir():
        raise ApiError("PATH_NOT_FOUND", f"Path is not a directory: {path}", 422)
    if not os.access(resolved, os.R_OK | os.X_OK):
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


async def _ingest_batch_file(
    db: AsyncSession, *, file_path: Path, inferred: BatchBoard | None, source: ImageSource
) -> FileResult:
    """Ingests one file already on a filesystem the backend can read, in place — no copy.

    Hashing the file and decoding its header are synchronous, CPU- and disk-bound, and run once
    per discovered file. `POST /inspections/scan` calls this from the API's own event loop, so
    without `to_thread` a folder with a few hundred boards would stall every other request in
    the process (health checks, SSE, chat) until the scan finished.
    """
    original_path = str(file_path)
    if await _is_known_path(db, original_path):
        return FileResult(path=original_path, outcome="skipped", reason="already known")

    if inferred is None:
        return FileResult(
            path=original_path, outcome="skipped", reason="not under a batch subdirectory"
        )

    batch = await _get_or_create_batch(db, inferred.batch_number)
    checksum = await asyncio.to_thread(sha256_checksum, file_path)

    try:
        meta = await asyncio.to_thread(read_image_metadata, file_path)
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


async def _enqueue_ingested(results: list[FileResult]) -> None:
    """Enqueues each newly-ingested image for inference (FR-04) and publishes its SSE event
    (FR-14) only after its row has been committed — the worker (and any listening client)
    runs in a separate process/connection and won't see an uncommitted row, so this must
    never run before `db.commit()`.

    Ingestion has already succeeded by the time this runs (the rows are durably `QUEUED` or
    `FAILED`), so a broker/Redis hiccup here must not fail the whole request or stop the rest
    of the batch from being processed — both are best-effort, logged and skipped rather than
    raised. `.delay()` is a blocking network round-trip to Redis; offloading it to a thread
    keeps a large batch from stalling the event loop for every other concurrent request.
    """
    for result in results:
        if result.outcome == "ingested" and result.image_id is not None:
            try:
                await asyncio.to_thread(run_inference.delay, str(result.image_id))
            except Exception:
                logger.exception(
                    "Failed to enqueue inference for inspection_image_id=%s", result.image_id
                )
            await publish_event(
                "inspection.created", {"id": str(result.image_id), "status": "QUEUED"}
            )
        elif result.outcome == "failed" and result.image_id is not None:
            await publish_event(
                "inspection.failed",
                {"id": str(result.image_id), "status": "FAILED", "reason": result.reason},
            )


async def scan_directory(db: AsyncSession, path: Path, *, source: ImageSource) -> ScanSummary:
    """Shared by both the one-off `/scan` endpoint and each watch-mode poll (`source` differs
    only in which value is stamped on the resulting `InspectionImage.source`).
    """
    await validate_directory_path(path)
    root = to_container_path(path)

    # Walks every batch subdirectory; off the event loop for the same reason as the per-file
    # work below.
    files = await asyncio.to_thread(iter_batch_files, root)
    results = [
        await _ingest_batch_file(
            db, file_path=f, inferred=infer_batch_and_board(root, f), source=source
        )
        for f in files
    ]
    return await _finish_directory_ingestion(db, path=path, discovered=len(files), results=results)


async def _finish_directory_ingestion(
    db: AsyncSession, *, path: Path, discovered: int, results: list[FileResult]
) -> ScanSummary:
    await db.commit()
    await _enqueue_ingested(results)

    # Rows keep the container path they were opened through; what's reported back to the
    # operator is the host path they actually recognize.
    for result in results:
        result.path = str(to_host_path(result.path))

    counts = Counter(r.outcome for r in results)
    return ScanSummary(
        path=str(path),
        discovered=discovered,
        ingested=counts["ingested"],
        duplicate=counts["duplicate"],
        failed=counts["failed"],
        skipped=counts["skipped"],
        files=results,
    )


async def get_ingestion_status(db: AsyncSession) -> IngestionStatus:
    from app.settings import service as settings_service

    watch_root_path = await settings_service.get_config_value(db, "watch_root_path")
    watch_mode_enabled = bool(
        await settings_service.get_config_value(db, "watch_mode_enabled", True)
    )

    files_discovered = (
        await db.scalar(
            select(func.count())
            .select_from(InspectionImage)
            .where(InspectionImage.source == ImageSource.WATCH_FOLDER)
        )
        or 0
    )
    files_failed = (
        await db.scalar(
            select(func.count())
            .select_from(InspectionImage)
            .where(
                InspectionImage.source == ImageSource.WATCH_FOLDER,
                InspectionImage.status == ImageStatus.FAILED,
            )
        )
        or 0
    )
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
