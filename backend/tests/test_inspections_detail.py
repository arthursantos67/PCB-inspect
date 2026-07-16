"""GET /api/v1/inspections/{id} and GET /api/v1/inspections/{id}/image (Issue 10, FE-03,
section 11.5) — the analysis detail screen's data source: board/batch metadata, reportable
detections with model version traceability, processing duration, and local-disk image
serving for the annotated-image viewer.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyses.service import create_baseline_analysis
from app.models import Batch, Board, Detection, InspectionImage, ModelVersion
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


async def _make_model_version(db: AsyncSession, version: str = "v1.0.0") -> ModelVersion:
    model_version = ModelVersion(version=version, weights_path="/weights/best.pt", is_active=True)
    db.add(model_version)
    await db.flush()
    return model_version


async def _make_board(db: AsyncSession, batch_number: str, board_number: str) -> Board:
    batch = Batch(batch_number=batch_number)
    db.add(batch)
    await db.flush()
    board = Board(batch_id=batch.id, board_number=board_number)
    db.add(board)
    await db.flush()
    return board


async def _make_image(
    db: AsyncSession,
    board: Board | None,
    original_path: Path,
    *,
    status: ImageStatus = ImageStatus.QUEUED,
    annotated_path: Path | None = None,
    created_at: datetime | None = None,
    processed_at: datetime | None = None,
) -> InspectionImage:
    image = InspectionImage(
        board_id=board.id if board is not None else None,
        source=ImageSource.WATCH_FOLDER,
        original_path=str(original_path),
        annotated_path=str(annotated_path) if annotated_path is not None else None,
        checksum_sha256=uuid.uuid4().hex,
        status=status,
        created_at=created_at or datetime.now(UTC),
        processed_at=processed_at,
    )
    db.add(image)
    await db.flush()
    return image


async def _make_detection(
    db: AsyncSession,
    image: InspectionImage,
    model_version: ModelVersion,
    *,
    confidence: Decimal = Decimal("0.900"),
    is_reported: bool = True,
) -> Detection:
    detection = Detection(
        image_id=image.id,
        defect_type="short",
        bbox={"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4},
        confidence=confidence,
        is_reported=is_reported,
        model_version_id=model_version.id,
    )
    db.add(detection)
    await db.flush()
    return detection


def _write_jpeg(path: Path, color: tuple[int, int, int] = (255, 0, 0)) -> None:
    Image.new("RGB", (32, 32), color).save(path, format="JPEG")


# --- GET /api/v1/inspections/{id} — detail shape (section 11.5) ----------------------------


async def test_get_inspection_returns_board_detections_and_model_version(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path
) -> None:
    token = await _setup_account(client)
    model_version = await _make_model_version(db_session)
    board = await _make_board(db_session, "BATCH-001", "board-1")
    original = tmp_path / "board.jpg"
    _write_jpeg(original)
    created_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    processed_at = created_at + timedelta(seconds=2, milliseconds=500)
    image = await _make_image(
        db_session,
        board,
        original,
        status=ImageStatus.DETECTED,
        created_at=created_at,
        processed_at=processed_at,
    )
    detection = await _make_detection(db_session, image, model_version)
    await db_session.commit()

    response = await client.get(
        f"/api/v1/inspections/{image.id}", headers=_auth_headers(token)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(image.id)
    assert body["status"] == "DETECTED"
    assert body["board"] == {"board_number": "board-1", "batch_number": "BATCH-001"}
    assert body["duration_ms"] == 2500
    assert len(body["detections"]) == 1
    assert body["detections"][0]["id"] == str(detection.id)
    assert body["detections"][0]["defect_type"] == "short"
    assert body["detections"][0]["model_version"] == "v1.0.0"
    assert body["detections"][0]["confidence"] == "0.900"
    assert body["detections"][0]["review"] == "unreviewed"
    assert body["detections"][0]["source"] == "model"
    assert body["disposition"] is None


async def test_get_inspection_omits_unreported_detections(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path
) -> None:
    """RV-03/RN-07: a detection below the report threshold is stored but never surfaced in
    the interface — the detail screen follows the same rule as the dashboard/aggregates.
    """
    token = await _setup_account(client)
    model_version = await _make_model_version(db_session)
    original = tmp_path / "board.jpg"
    _write_jpeg(original)
    image = await _make_image(db_session, None, original, status=ImageStatus.PROCESSING)
    await _make_detection(db_session, image, model_version, is_reported=False)
    await db_session.commit()

    response = await client.get(
        f"/api/v1/inspections/{image.id}", headers=_auth_headers(token)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["detections"] == []
    assert body["board"] == {"board_number": None, "batch_number": None}
    assert body["duration_ms"] is None


async def test_get_inspection_includes_analysis_once_completed(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path
) -> None:
    token = await _setup_account(client)
    model_version = await _make_model_version(db_session)
    original = tmp_path / "board.jpg"
    _write_jpeg(original)
    image = await _make_image(db_session, None, original, status=ImageStatus.DETECTED)
    detection = await _make_detection(db_session, image, model_version)
    await create_baseline_analysis(db_session, image, [detection])
    await db_session.commit()

    response = await client.get(
        f"/api/v1/inspections/{image.id}", headers=_auth_headers(token)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["analysis"]["source"] == "knowledge_base"
    assert body["analysis"]["per_defect"][0]["detection_id"] == str(detection.id)


async def test_get_inspection_includes_review_history_on_analysis(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path
) -> None:
    """FR-10/Issue 33: the detail screen's `analysis.reviews` must match `GET
    /api/v1/analyses/{id}` — this is the shape the frontend's `ReviewPanel` actually reads,
    not just the analyses-router's own GET endpoint.
    """
    token = await _setup_account(client)
    model_version = await _make_model_version(db_session)
    original = tmp_path / "board.jpg"
    _write_jpeg(original)
    image = await _make_image(db_session, None, original, status=ImageStatus.DETECTED)
    detection = await _make_detection(db_session, image, model_version)
    analysis = await create_baseline_analysis(db_session, image, [detection])
    await db_session.commit()

    review_response = await client.post(
        f"/api/v1/analyses/{analysis.id}/review",
        json={"action": "validated", "comment": "Looks correct."},
        headers=_auth_headers(token),
    )
    assert review_response.status_code == 200, review_response.text

    response = await client.get(
        f"/api/v1/inspections/{image.id}", headers=_auth_headers(token)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["review_status"] == "VALIDATED"
    assert len(body["analysis"]["reviews"]) == 1
    assert body["analysis"]["reviews"][0]["action"] == "validated"
    assert body["analysis"]["reviews"][0]["comment"] == "Looks correct."


async def test_get_inspection_returns_404_for_unknown_id(client: AsyncClient) -> None:
    token = await _setup_account(client)
    response = await client.get(
        "/api/v1/inspections/00000000-0000-0000-0000-000000000000",
        headers=_auth_headers(token),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INSPECTION_NOT_FOUND"


async def test_get_inspection_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/inspections/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 401


# --- GET /api/v1/inspections/{id}/image?variant= (Local Image Serving) ---------------------


async def test_get_inspection_image_original_streams_file_bytes(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path
) -> None:
    token = await _setup_account(client)
    original = tmp_path / "board.jpg"
    _write_jpeg(original, color=(10, 20, 30))
    image = await _make_image(db_session, None, original)
    await db_session.commit()

    response = await client.get(
        f"/api/v1/inspections/{image.id}/image?variant=original", headers=_auth_headers(token)
    )

    assert response.status_code == 200
    assert response.content == original.read_bytes()
    assert response.headers["content-type"] == "image/jpeg"


async def test_get_inspection_image_annotated_streams_file_bytes(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path
) -> None:
    token = await _setup_account(client)
    original = tmp_path / "board.jpg"
    annotated = tmp_path / "board-annotated.jpg"
    _write_jpeg(original)
    _write_jpeg(annotated, color=(200, 0, 0))
    image = await _make_image(
        db_session, None, original, status=ImageStatus.DETECTED, annotated_path=annotated
    )
    await db_session.commit()

    response = await client.get(
        f"/api/v1/inspections/{image.id}/image?variant=annotated", headers=_auth_headers(token)
    )

    assert response.status_code == 200
    assert response.content == annotated.read_bytes()


async def test_get_inspection_image_defaults_to_original_variant(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path
) -> None:
    token = await _setup_account(client)
    original = tmp_path / "board.jpg"
    _write_jpeg(original)
    image = await _make_image(db_session, None, original)
    await db_session.commit()

    response = await client.get(
        f"/api/v1/inspections/{image.id}/image", headers=_auth_headers(token)
    )

    assert response.status_code == 200
    assert response.content == original.read_bytes()


async def test_get_inspection_image_annotated_not_ready_returns_409(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path
) -> None:
    token = await _setup_account(client)
    original = tmp_path / "board.jpg"
    _write_jpeg(original)
    image = await _make_image(db_session, None, original, status=ImageStatus.PROCESSING)
    await db_session.commit()

    response = await client.get(
        f"/api/v1/inspections/{image.id}/image?variant=annotated", headers=_auth_headers(token)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INSPECTION_NOT_READY"


async def test_get_inspection_image_unknown_inspection_returns_404(client: AsyncClient) -> None:
    token = await _setup_account(client)
    response = await client.get(
        "/api/v1/inspections/00000000-0000-0000-0000-000000000000/image",
        headers=_auth_headers(token),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INSPECTION_NOT_FOUND"


async def test_get_inspection_image_invalid_variant_returns_400(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path
) -> None:
    token = await _setup_account(client)
    original = tmp_path / "board.jpg"
    _write_jpeg(original)
    image = await _make_image(db_session, None, original)
    await db_session.commit()

    response = await client.get(
        f"/api/v1/inspections/{image.id}/image?variant=bogus", headers=_auth_headers(token)
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_get_inspection_image_requires_auth(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path
) -> None:
    original = tmp_path / "board.jpg"
    _write_jpeg(original)
    image = await _make_image(db_session, None, original)
    await db_session.commit()

    response = await client.get(f"/api/v1/inspections/{image.id}/image")

    assert response.status_code == 401


@pytest.mark.parametrize("variant", ["original", "annotated"])
async def test_get_inspection_image_missing_file_on_disk_returns_404(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path, variant: str
) -> None:
    token = await _setup_account(client)
    missing = tmp_path / "gone.jpg"
    image = await _make_image(
        db_session,
        None,
        missing,
        status=ImageStatus.DETECTED,
        annotated_path=missing if variant == "annotated" else None,
    )
    await db_session.commit()

    response = await client.get(
        f"/api/v1/inspections/{image.id}/image?variant={variant}", headers=_auth_headers(token)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
