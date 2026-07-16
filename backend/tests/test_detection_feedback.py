"""POST /api/v1/detections/{id}/feedback (FR-10, Issue 33) — per-detection confirm/
false-positive feedback, independent of the analysis-level review, audited per FR-16.
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Detection, InspectionImage, ModelVersion
from app.models.enums import DefectType, DetectionReview, ImageSource, ImageStatus

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


async def _make_detection(db: AsyncSession) -> Detection:
    model_version = ModelVersion(version="v1.0.0", weights_path="/weights/best.pt", is_active=True)
    db.add(model_version)
    await db.flush()
    image = InspectionImage(
        source=ImageSource.WATCH_FOLDER,
        original_path=f"/tmp/{uuid.uuid4()}.jpg",
        checksum_sha256=uuid.uuid4().hex,
        status=ImageStatus.DETECTED,
    )
    db.add(image)
    await db.flush()
    detection = Detection(
        image_id=image.id,
        defect_type=DefectType.MOUSE_BITE,
        bbox={"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4},
        confidence=Decimal("0.900"),
        is_reported=True,
        model_version_id=model_version.id,
    )
    db.add(detection)
    await db.flush()
    return detection


@pytest.mark.parametrize("review", ["confirmed", "false_positive"])
async def test_feedback_sets_review_and_reviewer(
    client: AsyncClient, db_session: AsyncSession, review: str
) -> None:
    token = await _setup_account(client)
    detection = await _make_detection(db_session)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/detections/{detection.id}/feedback",
        json={"review": review},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["review"] == review
    assert body["reviewed_by"] is not None


async def test_feedback_is_independent_of_analysis_review(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Marking a detection doesn't require (or touch) any `Analysis` row at all."""
    token = await _setup_account(client)
    detection = await _make_detection(db_session)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/detections/{detection.id}/feedback",
        json={"review": "false_positive"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 200


async def test_feedback_produces_audit_log_entry(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    detection = await _make_detection(db_session)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/detections/{detection.id}/feedback",
        json={"review": "confirmed"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 200

    entries = (
        await db_session.scalars(
            select(AuditLog).where(
                AuditLog.entity_type == "detection", AuditLog.entity_id == detection.id
            )
        )
    ).all()
    assert len(entries) == 1
    assert entries[0].action == "detection.reviewed"
    assert entries[0].payload == {
        "review": "confirmed",
        "previous": DetectionReview.UNREVIEWED.value,
    }


async def test_feedback_rejects_unreviewed_as_a_value(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    detection = await _make_detection(db_session)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/detections/{detection.id}/feedback",
        json={"review": "unreviewed"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_feedback_returns_404_for_unknown_detection(client: AsyncClient) -> None:
    token = await _setup_account(client)
    response = await client.post(
        f"/api/v1/detections/{uuid.uuid4()}/feedback",
        json={"review": "confirmed"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


async def test_feedback_requires_authentication(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    detection = await _make_detection(db_session)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/detections/{detection.id}/feedback", json={"review": "confirmed"}
    )
    assert response.status_code == 401
