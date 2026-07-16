"""POST /api/v1/inspections/{id}/annotations (FR-10, Issue 10, Issue 33) — annotating a
defect the model missed by drawing a bbox + class directly in the image viewer creates a
`Detection` row flagged `source=manual`, pre-confirmed, distinguishable from model output,
and audited per FR-16.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Detection, InspectionImage
from app.models.enums import ImageSource, ImageStatus

ACCOUNT = {
    "email": "operator@pcb-inspect.local",
    "password": "correct-horse-battery",
    "full_name": "Operator",
}

VALID_BBOX = {"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4}


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _setup_account(client: AsyncClient) -> str:
    response = await client.post("/api/v1/auth/setup", json=ACCOUNT)
    return response.json()["access_token"]


async def _make_image(db: AsyncSession) -> InspectionImage:
    image = InspectionImage(
        source=ImageSource.WATCH_FOLDER,
        original_path=f"/tmp/{uuid.uuid4()}.jpg",
        checksum_sha256=uuid.uuid4().hex,
        status=ImageStatus.COMPLETED,
    )
    db.add(image)
    await db.flush()
    return image


async def test_annotation_creates_detection_flagged_as_manual(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    image = await _make_image(db_session)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/inspections/{image.id}/annotations",
        json={"defect_type": "spurious_copper", "bbox": VALID_BBOX},
        headers=_auth_headers(token),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["defect_type"] == "spurious_copper"
    assert body["source"] == "manual"
    assert body["review"] == "confirmed"  # the operator drawing it IS the confirmation
    assert body["is_reported"] is True
    assert body["model_version"] is None
    assert body["bbox"] == VALID_BBOX


async def test_annotation_is_distinguishable_from_model_output_on_detail_screen(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    image = await _make_image(db_session)
    await db_session.commit()

    await client.post(
        f"/api/v1/inspections/{image.id}/annotations",
        json={"defect_type": "spur", "bbox": VALID_BBOX},
        headers=_auth_headers(token),
    )

    detail = await client.get(
        f"/api/v1/inspections/{image.id}", headers=_auth_headers(token)
    )
    assert detail.status_code == 200
    detections = detail.json()["detections"]
    assert len(detections) == 1
    assert detections[0]["source"] == "manual"


async def test_annotation_persists_as_detection_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    image = await _make_image(db_session)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/inspections/{image.id}/annotations",
        json={"defect_type": "open_circuit", "bbox": VALID_BBOX},
        headers=_auth_headers(token),
    )
    detection_id = uuid.UUID(response.json()["id"])

    detection = await db_session.get(Detection, detection_id)
    assert detection is not None
    assert detection.model_version_id is None
    assert detection.image_id == image.id


async def test_annotation_produces_audit_log_entry(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    image = await _make_image(db_session)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/inspections/{image.id}/annotations",
        json={"defect_type": "missing_hole", "bbox": VALID_BBOX},
        headers=_auth_headers(token),
    )
    detection_id = response.json()["id"]

    entries = (
        await db_session.scalars(
            select(AuditLog).where(
                AuditLog.entity_type == "detection", AuditLog.entity_id == uuid.UUID(detection_id)
            )
        )
    ).all()
    assert len(entries) == 1
    assert entries[0].action == "detection.annotated"


async def test_annotation_rejects_out_of_bounds_bbox(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    image = await _make_image(db_session)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/inspections/{image.id}/annotations",
        json={"defect_type": "short", "bbox": {"x1": -0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4}},
        headers=_auth_headers(token),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_annotation_rejects_inverted_bbox(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    image = await _make_image(db_session)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/inspections/{image.id}/annotations",
        json={"defect_type": "short", "bbox": {"x1": 0.5, "y1": 0.1, "x2": 0.4, "y2": 0.4}},
        headers=_auth_headers(token),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_annotation_returns_404_for_unknown_inspection(client: AsyncClient) -> None:
    token = await _setup_account(client)
    response = await client.post(
        f"/api/v1/inspections/{uuid.uuid4()}/annotations",
        json={"defect_type": "short", "bbox": VALID_BBOX},
        headers=_auth_headers(token),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INSPECTION_NOT_FOUND"


async def test_annotation_requires_authentication(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    image = await _make_image(db_session)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/inspections/{image.id}/annotations",
        json={"defect_type": "short", "bbox": VALID_BBOX},
    )
    assert response.status_code == 401
