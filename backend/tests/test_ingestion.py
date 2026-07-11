from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ApiError
from app.ingestion import service as ingestion_service
from app.ingestion.naming import infer_batch_and_board
from app.ingestion.watcher import poll_watch_root_once
from app.main import app as fastapi_app
from app.models import Batch, Board, InspectionImage
from app.models.enums import ImageSource, ImageStatus

ACCOUNT = {
    "email": "operator@pcb-inspect.local",
    "password": "correct-horse-battery",
    "full_name": "Operator",
}


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _setup_account(client: AsyncClient) -> str:
    response = await client.post("/api/v1/auth/setup", json=ACCOUNT)
    return response.json()["access_token"]


def _write_jpeg(path: Path, color: tuple[int, int, int] = (255, 0, 0)) -> None:
    Image.new("RGB", (32, 32), color).save(path, format="JPEG")


def _write_png(path: Path, color: tuple[int, int, int] = (0, 255, 0)) -> None:
    Image.new("RGB", (32, 32), color).save(path, format="PNG")


@pytest.fixture
def watch_root(tmp_path: Path) -> Path:
    root = tmp_path / "watch-root"
    root.mkdir()
    return root


@pytest.fixture
def isolated_app_data_dir(tmp_path: Path):
    """The import endpoint writes uploaded bytes under `settings.app_data_dir` (FR-03) — the
    real default (`/data/app-data`, only valid inside the Docker volume mount) isn't writable
    outside a container, so tests override it with a temp directory via dependency injection.
    """
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    overridden = get_settings().model_copy(update={"app_data_dir": data_dir})
    fastapi_app.dependency_overrides[get_settings] = lambda: overridden
    yield data_dir
    fastapi_app.dependency_overrides.pop(get_settings, None)


class _FakeInferenceTask:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def delay(self, inspection_image_id: str) -> None:
        self.calls.append(inspection_image_id)


@pytest.fixture(autouse=True)
def enqueue_stub(monkeypatch: pytest.MonkeyPatch) -> _FakeInferenceTask:
    """Stubs the Celery enqueue call (FR-04) for every ingestion test: there's no Redis
    broker here, and running the real task eagerly would recurse `asyncio.run()` into the
    event loop already driving this async request/test — the task itself is covered in
    isolation by `tests/test_pipeline_tasks.py`.
    """
    stub = _FakeInferenceTask()
    monkeypatch.setattr(ingestion_service, "run_inference", stub)
    return stub


# --- Naming convention (pure unit tests, no DB) ---------------------------------------------


def test_infer_batch_and_board_from_immediate_subdirectory(tmp_path: Path) -> None:
    result = infer_batch_and_board(tmp_path, tmp_path / "BATCH-42" / "board-7.jpg")
    assert result is not None
    assert result.batch_number == "BATCH-42"
    assert result.board_number == "board-7"


def test_infer_batch_and_board_none_for_root_level_file(tmp_path: Path) -> None:
    assert infer_batch_and_board(tmp_path, tmp_path / "stray.jpg") is None


def test_infer_batch_and_board_none_for_deeper_nesting(tmp_path: Path) -> None:
    assert infer_batch_and_board(tmp_path, tmp_path / "BATCH-1" / "sub" / "board.jpg") is None


# --- Watch-root / scan path validation -------------------------------------------------------


async def test_scan_rejects_missing_path(client: AsyncClient, tmp_path: Path) -> None:
    token = await _setup_account(client)
    response = await client.post(
        "/api/v1/inspections/scan",
        json={"path": str(tmp_path / "does-not-exist")},
        headers=_auth_headers(token),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PATH_NOT_FOUND"


async def test_validate_directory_path_rejects_unreadable_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    directory = tmp_path / "unreadable"
    directory.mkdir()
    monkeypatch.setattr(ingestion_service.os, "access", lambda *args, **kwargs: False)

    with pytest.raises(ApiError) as exc_info:
        await ingestion_service.validate_directory_path(directory)
    assert exc_info.value.code == "PATH_NOT_READABLE"


async def test_update_config_rejects_invalid_watch_root_path(
    client: AsyncClient, tmp_path: Path
) -> None:
    token = await _setup_account(client)
    response = await client.patch(
        "/api/v1/settings/config",
        json={"config": {"watch_root_path": str(tmp_path / "nope")}},
        headers=_auth_headers(token),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PATH_NOT_FOUND"


# --- One-off scan: convention, no mutation, zero-copy -----------------------------------------


async def test_scan_applies_convention_and_ingests_every_valid_image(
    client: AsyncClient, db_session: AsyncSession, watch_root: Path
) -> None:
    token = await _setup_account(client)
    batch_dir = watch_root / "BATCH-001"
    batch_dir.mkdir()
    _write_jpeg(batch_dir / "board-1.jpg")
    _write_png(batch_dir / "board-2.png")
    (watch_root / "stray-at-root.jpg").write_bytes(b"not-a-real-image-and-not-in-a-batch")

    response = await client.post(
        "/api/v1/inspections/scan", json={"path": str(watch_root)}, headers=_auth_headers(token)
    )

    assert response.status_code == 202
    body = response.json()
    assert body["discovered"] == 2  # only files under a batch subdirectory count
    assert body["ingested"] == 2
    assert body["failed"] == 0
    assert body["duplicate"] == 0

    batch = await db_session.scalar(select(Batch).where(Batch.batch_number == "BATCH-001"))
    assert batch is not None
    boards = (await db_session.scalars(select(Board).where(Board.batch_id == batch.id))).all()
    assert {b.board_number for b in boards} == {"board-1", "board-2"}


async def test_scan_never_mutates_or_copies_original_files(
    client: AsyncClient, db_session: AsyncSession, watch_root: Path
) -> None:
    token = await _setup_account(client)
    batch_dir = watch_root / "BATCH-001"
    batch_dir.mkdir()
    file_path = batch_dir / "board-1.jpg"
    _write_jpeg(file_path)
    original_bytes = file_path.read_bytes()
    original_mtime = file_path.stat().st_mtime

    await client.post(
        "/api/v1/inspections/scan", json={"path": str(watch_root)}, headers=_auth_headers(token)
    )

    assert file_path.read_bytes() == original_bytes
    assert file_path.stat().st_mtime == original_mtime
    assert list(batch_dir.iterdir()) == [file_path]

    image = await db_session.scalar(select(InspectionImage))
    assert image is not None
    assert image.original_path == str(file_path)  # zero-copy: references the file in place


async def test_scan_rejects_duplicate_checksum_within_same_batch(
    client: AsyncClient, db_session: AsyncSession, watch_root: Path
) -> None:
    token = await _setup_account(client)
    batch_dir = watch_root / "BATCH-001"
    batch_dir.mkdir()
    original = batch_dir / "board-1.jpg"
    _write_jpeg(original)
    (batch_dir / "board-1-copy.jpg").write_bytes(original.read_bytes())

    response = await client.post(
        "/api/v1/inspections/scan", json={"path": str(watch_root)}, headers=_auth_headers(token)
    )

    body = response.json()
    assert body["discovered"] == 2
    assert body["ingested"] == 1
    assert body["duplicate"] == 1

    count = await db_session.scalar(select(func.count()).select_from(InspectionImage))
    assert count == 1


async def test_scan_records_invalid_file_as_failed_without_affecting_the_rest(
    client: AsyncClient, db_session: AsyncSession, watch_root: Path
) -> None:
    token = await _setup_account(client)
    batch_dir = watch_root / "BATCH-001"
    batch_dir.mkdir()
    _write_jpeg(batch_dir / "good.jpg")
    (batch_dir / "corrupted.jpg").write_bytes(b"not-an-image")

    response = await client.post(
        "/api/v1/inspections/scan", json={"path": str(watch_root)}, headers=_auth_headers(token)
    )

    body = response.json()
    assert body["discovered"] == 2
    assert body["ingested"] == 1
    assert body["failed"] == 1

    failed_image = await db_session.scalar(
        select(InspectionImage).where(InspectionImage.status == ImageStatus.FAILED)
    )
    assert failed_image is not None
    assert failed_image.failure_reason
    assert failed_image.width is None
    assert failed_image.height is None


# --- Ad hoc import -----------------------------------------------------------------------------


async def test_import_uploads_and_registers_a_stray_file(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path, isolated_app_data_dir: Path
) -> None:
    token = await _setup_account(client)
    stray = tmp_path / "stray.png"
    _write_png(stray)

    with stray.open("rb") as fh:
        response = await client.post(
            "/api/v1/inspections/import",
            files={"files": ("stray.png", fh, "image/png")},
            headers=_auth_headers(token),
        )

    assert response.status_code == 202
    assert response.json()["ingested"] == 1

    image = await db_session.scalar(
        select(InspectionImage).where(InspectionImage.source == ImageSource.MANUAL_IMPORT)
    )
    assert image is not None
    assert image.board_id is None
    assert image.original_path != str(stray)  # a copy, written into app-data (FR-03)
    assert Path(image.original_path).read_bytes() == stray.read_bytes()
    assert stray.exists()  # the operator's original file is left alone


async def test_import_rejects_duplicate_checksum(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path, isolated_app_data_dir: Path
) -> None:
    token = await _setup_account(client)
    stray = tmp_path / "stray.png"
    _write_png(stray)

    async def _import(name: str) -> dict[str, object]:
        with stray.open("rb") as fh:
            response = await client.post(
                "/api/v1/inspections/import",
                files={"files": (name, fh, "image/png")},
                headers=_auth_headers(token),
            )
        return response.json()  # type: ignore[no-any-return]

    first = await _import("stray.png")
    assert first["ingested"] == 1

    second = await _import("stray-again.png")
    assert second["ingested"] == 0
    assert second["duplicate"] == 1

    count = await db_session.scalar(select(func.count()).select_from(InspectionImage))
    assert count == 1


# --- Watch mode (continuous) --------------------------------------------------------------------


async def test_watch_mode_ingests_new_files_and_skips_already_known_ones(
    client: AsyncClient, db_session: AsyncSession, watch_root: Path
) -> None:
    token = await _setup_account(client)
    await client.patch(
        "/api/v1/settings/config",
        json={"config": {"watch_root_path": str(watch_root), "watch_mode_enabled": True}},
        headers=_auth_headers(token),
    )

    batch_dir = watch_root / "BATCH-001"
    batch_dir.mkdir()
    _write_jpeg(batch_dir / "board-1.jpg")

    first_poll = await poll_watch_root_once(db_session)
    assert first_poll is not None
    assert first_poll.ingested == 1

    image = await db_session.scalar(
        select(InspectionImage).where(InspectionImage.source == ImageSource.WATCH_FOLDER)
    )
    assert image is not None

    second_poll = await poll_watch_root_once(db_session)
    assert second_poll is not None
    assert second_poll.ingested == 0
    assert second_poll.skipped == 1  # already-known path, not re-ingested every cycle


async def test_watch_mode_is_a_noop_when_paused(
    client: AsyncClient, db_session: AsyncSession, watch_root: Path
) -> None:
    token = await _setup_account(client)
    await client.patch(
        "/api/v1/settings/config",
        json={"config": {"watch_root_path": str(watch_root), "watch_mode_enabled": False}},
        headers=_auth_headers(token),
    )
    batch_dir = watch_root / "BATCH-001"
    batch_dir.mkdir()
    _write_jpeg(batch_dir / "board-1.jpg")

    assert await poll_watch_root_once(db_session) is None

    status_response = await client.get(
        "/api/v1/inspections/ingestion-status", headers=_auth_headers(token)
    )
    assert status_response.json()["status"] == "paused"


async def test_ingestion_status_reports_watching_state_and_counts(
    client: AsyncClient, db_session: AsyncSession, watch_root: Path
) -> None:
    token = await _setup_account(client)

    not_configured = await client.get(
        "/api/v1/inspections/ingestion-status", headers=_auth_headers(token)
    )
    assert not_configured.json()["status"] == "not_configured"

    await client.patch(
        "/api/v1/settings/config",
        json={"config": {"watch_root_path": str(watch_root)}},
        headers=_auth_headers(token),
    )
    watching = await client.get(
        "/api/v1/inspections/ingestion-status", headers=_auth_headers(token)
    )
    assert watching.json()["status"] == "watching"

    batch_dir = watch_root / "BATCH-001"
    batch_dir.mkdir()
    _write_jpeg(batch_dir / "board-1.jpg")
    await poll_watch_root_once(db_session)

    after_poll = await client.get(
        "/api/v1/inspections/ingestion-status", headers=_auth_headers(token)
    )
    body = after_poll.json()
    assert body["files_discovered"] == 1
    assert body["files_ingested"] == 1
    assert body["files_failed"] == 0


# --- Enqueue on ingestion (FR-04) ------------------------------------------------------------


async def test_scan_enqueues_every_ingested_image(
    client: AsyncClient, watch_root: Path, enqueue_stub: _FakeInferenceTask
) -> None:
    token = await _setup_account(client)
    batch_dir = watch_root / "BATCH-001"
    batch_dir.mkdir()
    _write_jpeg(batch_dir / "board-1.jpg")
    _write_png(batch_dir / "board-2.png")

    response = await client.post(
        "/api/v1/inspections/scan", json={"path": str(watch_root)}, headers=_auth_headers(token)
    )

    body = response.json()
    ingested_ids = {f["image_id"] for f in body["files"] if f["outcome"] == "ingested"}
    assert len(ingested_ids) == 2
    assert set(enqueue_stub.calls) == {str(i) for i in ingested_ids}


async def test_scan_does_not_enqueue_duplicate_or_failed_files(
    client: AsyncClient, watch_root: Path, enqueue_stub: _FakeInferenceTask
) -> None:
    token = await _setup_account(client)
    batch_dir = watch_root / "BATCH-001"
    batch_dir.mkdir()
    _write_jpeg(batch_dir / "good.jpg")
    (batch_dir / "corrupted.jpg").write_bytes(b"not-an-image")

    await client.post(
        "/api/v1/inspections/scan", json={"path": str(watch_root)}, headers=_auth_headers(token)
    )

    assert len(enqueue_stub.calls) == 1  # only the valid image is enqueued


async def test_import_enqueues_the_ingested_file(
    client: AsyncClient,
    tmp_path: Path,
    isolated_app_data_dir: Path,
    enqueue_stub: _FakeInferenceTask,
) -> None:
    token = await _setup_account(client)
    stray = tmp_path / "stray.png"
    _write_png(stray)

    with stray.open("rb") as fh:
        response = await client.post(
            "/api/v1/inspections/import",
            files={"files": ("stray.png", fh, "image/png")},
            headers=_auth_headers(token),
        )

    image_id = response.json()["files"][0]["image_id"]
    assert enqueue_stub.calls == [image_id]


# --- Progress query (FR-04) ------------------------------------------------------------------


async def test_get_progress_returns_current_status(
    client: AsyncClient, watch_root: Path
) -> None:
    token = await _setup_account(client)
    batch_dir = watch_root / "BATCH-001"
    batch_dir.mkdir()
    _write_jpeg(batch_dir / "board-1.jpg")

    scan_response = await client.post(
        "/api/v1/inspections/scan", json={"path": str(watch_root)}, headers=_auth_headers(token)
    )
    image_id = scan_response.json()["files"][0]["image_id"]

    progress = await client.get(
        f"/api/v1/inspections/{image_id}", headers=_auth_headers(token)
    )

    assert progress.status_code == 200
    body = progress.json()
    assert body["id"] == image_id
    assert body["status"] == "QUEUED"
    assert body["failure_reason"] is None


async def test_get_progress_returns_404_for_unknown_id(client: AsyncClient) -> None:
    token = await _setup_account(client)
    response = await client.get(
        "/api/v1/inspections/00000000-0000-0000-0000-000000000000",
        headers=_auth_headers(token),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INSPECTION_NOT_FOUND"
