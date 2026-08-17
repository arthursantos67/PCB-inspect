"""`GET /api/v1/batches` — the batch-first inspections list.

Covers the per-batch aggregates the screen shows (board counts, defect counts and rate,
weighted severity, worst-status-wins), RN-07 (unreported detections excluded), filtering and
pagination.

Rows are built directly against the ORM, same convention as tests/test_stats.py.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Batch, Board, Detection, InspectionImage, ModelVersion
from app.models.enums import DefectType, ImageSource, ImageStatus

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


async def _make_model_version(db: AsyncSession) -> ModelVersion:
    model_version = ModelVersion(version="v1.0.0", weights_path="/weights/best.pt", is_active=True)
    db.add(model_version)
    await db.flush()
    return model_version


async def _make_board(db: AsyncSession, batch_number: str, board_number: str) -> Board:
    batch = await db.scalar(select(Batch).where(Batch.batch_number == batch_number))
    if batch is None:
        batch = Batch(batch_number=batch_number)
        db.add(batch)
        await db.flush()
    board = Board(batch_id=batch.id, board_number=board_number)
    db.add(board)
    await db.flush()
    return board


async def _make_image(
    db: AsyncSession,
    board: Board,
    *,
    status: ImageStatus = ImageStatus.COMPLETED,
    created_at: datetime | None = None,
) -> InspectionImage:
    image = InspectionImage(
        board_id=board.id,
        source=ImageSource.WATCH_FOLDER,
        original_path=f"/tmp/{uuid.uuid4()}.jpg",
        checksum_sha256=uuid.uuid4().hex,
        status=status,
    )
    if created_at is not None:
        image.created_at = created_at
    db.add(image)
    await db.flush()
    return image


async def _make_detection(
    db: AsyncSession,
    image: InspectionImage,
    model_version: ModelVersion,
    defect_type: DefectType,
    *,
    is_reported: bool = True,
) -> Detection:
    detection = Detection(
        image_id=image.id,
        defect_type=defect_type,
        bbox={"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4},
        confidence=Decimal("0.900") if is_reported else Decimal("0.300"),
        is_reported=is_reported,
        model_version_id=model_version.id,
    )
    db.add(detection)
    await db.flush()
    return detection


async def _list(client: AsyncClient, token: str, **params: object) -> dict:
    response = await client.get("/api/v1/batches", params=params, headers=_auth_headers(token))
    assert response.status_code == 200, response.text
    return response.json()


async def test_list_batches_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/batches")

    assert response.status_code == 401


async def test_list_batches_aggregates_boards_and_defects(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    model_version = await _make_model_version(db_session)
    board_a = await _make_board(db_session, "BATCH-A", "BOARD-1")
    board_b = await _make_board(db_session, "BATCH-A", "BOARD-2")
    board_c = await _make_board(db_session, "BATCH-A", "BOARD-3")
    image_a = await _make_image(db_session, board_a)
    image_b = await _make_image(db_session, board_b)
    await _make_image(db_session, board_c)
    await _make_detection(db_session, image_a, model_version, DefectType.SHORT)
    await _make_detection(db_session, image_a, model_version, DefectType.SHORT)
    await _make_detection(db_session, image_b, model_version, DefectType.MOUSE_BITE)
    await db_session.commit()

    body = await _list(client, token)

    assert body["count"] == 1
    row = body["results"][0]
    assert row["batch_number"] == "BATCH-A"
    assert row["board_count"] == 3
    assert row["completed_count"] == 3
    assert row["boards_with_defects"] == 2
    assert row["defect_count"] == 3
    assert row["defect_rate"] == round(2 / 3, 4)
    assert row["defect_types"] == [
        {"defect_type": "short", "count": 2},
        {"defect_type": "mouse_bite", "count": 1},
    ]
    assert row["severity"] is not None


async def test_list_batches_excludes_unreported_detections(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """RN-07: only `is_reported` detections feed any aggregate."""
    token = await _setup_account(client)
    model_version = await _make_model_version(db_session)
    board = await _make_board(db_session, "BATCH-A", "BOARD-1")
    image = await _make_image(db_session, board)
    await _make_detection(db_session, image, model_version, DefectType.SHORT, is_reported=False)
    await db_session.commit()

    body = await _list(client, token)

    row = body["results"][0]
    assert row["defect_count"] == 0
    assert row["boards_with_defects"] == 0
    assert row["severity"] is None


async def test_batch_status_reflects_the_worst_in_flight_board(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    board_done = await _make_board(db_session, "BATCH-A", "BOARD-1")
    board_running = await _make_board(db_session, "BATCH-A", "BOARD-2")
    await _make_image(db_session, board_done, status=ImageStatus.COMPLETED)
    await _make_image(db_session, board_running, status=ImageStatus.PROCESSING)
    await db_session.commit()

    body = await _list(client, token)

    assert body["results"][0]["status"] == "PROCESSING"
    assert body["results"][0]["completed_count"] == 1


async def test_batch_status_flags_a_failure_over_everything_else(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    board_failed = await _make_board(db_session, "BATCH-A", "BOARD-1")
    board_running = await _make_board(db_session, "BATCH-A", "BOARD-2")
    await _make_image(db_session, board_failed, status=ImageStatus.FAILED)
    await _make_image(db_session, board_running, status=ImageStatus.PROCESSING)
    await db_session.commit()

    body = await _list(client, token)

    assert body["results"][0]["status"] == "FAILED"


async def test_list_batches_filters_by_batch_number_and_paginates(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    for index in range(3):
        board = await _make_board(db_session, f"BATCH-{index}", "BOARD-1")
        await _make_image(db_session, board)
    await db_session.commit()

    filtered = await _list(client, token, batch_number="batch-1")
    assert filtered["count"] == 1
    assert filtered["results"][0]["batch_number"] == "BATCH-1"

    first_page = await _list(client, token, page=1, page_size=2)
    assert first_page["count"] == 3
    assert len(first_page["results"]) == 2

    second_page = await _list(client, token, page=2, page_size=2)
    assert len(second_page["results"]) == 1


async def test_list_batches_filters_by_date_range(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    old_board = await _make_board(db_session, "BATCH-OLD", "BOARD-1")
    new_board = await _make_board(db_session, "BATCH-NEW", "BOARD-1")
    await _make_image(db_session, old_board, created_at=datetime.now(UTC) - timedelta(days=30))
    await _make_image(db_session, new_board)
    await db_session.commit()

    body = await _list(
        client, token, date_from=(datetime.now(UTC) - timedelta(days=1)).isoformat()
    )

    assert [row["batch_number"] for row in body["results"]] == ["BATCH-NEW"]


async def test_get_batch_returns_the_same_aggregate_as_the_list(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    model_version = await _make_model_version(db_session)
    board = await _make_board(db_session, "BATCH-A", "BOARD-1")
    image = await _make_image(db_session, board)
    await _make_detection(db_session, image, model_version, DefectType.SPUR)
    await db_session.commit()

    listed = (await _list(client, token))["results"][0]
    response = await client.get("/api/v1/batches/BATCH-A", headers=_auth_headers(token))

    assert response.status_code == 200
    assert response.json() == listed


async def test_get_unknown_batch_returns_404(client: AsyncClient) -> None:
    token = await _setup_account(client)

    response = await client.get("/api/v1/batches/NOPE", headers=_auth_headers(token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
