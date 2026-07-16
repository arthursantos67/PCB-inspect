"""POST /api/v1/analyses/{id}/review (FR-10, UC-8, Issue 33) — validating/rejecting an
analysis persists the action, actor, and optional comment as a queryable `AnalysisReview`
row, projects the latest action onto `Analysis.review_status`, and produces an `AuditLog`
record (FR-16).
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyses.service import create_baseline_analysis
from app.models import AuditLog, Detection, InspectionImage, ModelVersion
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


async def _make_analyzed_image(db: AsyncSession) -> tuple[InspectionImage, Detection]:
    model_version = await _make_model_version(db)
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
    return image, detection


async def test_validate_persists_action_actor_and_comment(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    image, detection = await _make_analyzed_image(db_session)
    analysis = await create_baseline_analysis(db_session, image, [detection])
    await db_session.commit()

    response = await client.post(
        f"/api/v1/analyses/{analysis.id}/review",
        json={"action": "validated", "comment": "Looks correct."},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["review_status"] == "VALIDATED"
    assert len(body["reviews"]) == 1
    assert body["reviews"][0]["action"] == "validated"
    assert body["reviews"][0]["comment"] == "Looks correct."
    assert body["reviews"][0]["reviewer_id"] is not None


async def test_reject_persists_action_and_is_queryable_later(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    image, detection = await _make_analyzed_image(db_session)
    analysis = await create_baseline_analysis(db_session, image, [detection])
    await db_session.commit()

    reject_response = await client.post(
        f"/api/v1/analyses/{analysis.id}/review",
        json={"action": "rejected", "comment": "Missed a defect."},
        headers=_auth_headers(token),
    )
    assert reject_response.status_code == 200, reject_response.text
    assert reject_response.json()["review_status"] == "REJECTED"

    # Queryable later, independent of this request — a fresh GET returns the same history.
    get_response = await client.get(
        f"/api/v1/analyses/{analysis.id}", headers=_auth_headers(token)
    )
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["review_status"] == "REJECTED"
    assert len(body["reviews"]) == 1
    assert body["reviews"][0]["action"] == "rejected"
    assert body["reviews"][0]["comment"] == "Missed a defect."


async def test_second_review_appends_history_and_updates_latest_status(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    image, detection = await _make_analyzed_image(db_session)
    analysis = await create_baseline_analysis(db_session, image, [detection])
    await db_session.commit()

    await client.post(
        f"/api/v1/analyses/{analysis.id}/review",
        json={"action": "rejected"},
        headers=_auth_headers(token),
    )
    second = await client.post(
        f"/api/v1/analyses/{analysis.id}/review",
        json={"action": "validated"},
        headers=_auth_headers(token),
    )

    assert second.status_code == 200
    body = second.json()
    assert body["review_status"] == "VALIDATED"
    assert len(body["reviews"]) == 2
    assert [r["action"] for r in body["reviews"]] == ["rejected", "validated"]


async def test_review_produces_audit_log_entry(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    image, detection = await _make_analyzed_image(db_session)
    analysis = await create_baseline_analysis(db_session, image, [detection])
    await db_session.commit()

    response = await client.post(
        f"/api/v1/analyses/{analysis.id}/review",
        json={"action": "validated"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 200

    entries = (
        await db_session.scalars(
            select(AuditLog).where(
                AuditLog.entity_type == "analysis", AuditLog.entity_id == analysis.id
            )
        )
    ).all()
    assert len(entries) == 1
    assert entries[0].action == "analysis.validated"


@pytest.mark.parametrize("action", ["validated", "rejected"])
async def test_comment_is_optional(
    client: AsyncClient, db_session: AsyncSession, action: str
) -> None:
    token = await _setup_account(client)
    image, detection = await _make_analyzed_image(db_session)
    analysis = await create_baseline_analysis(db_session, image, [detection])
    await db_session.commit()

    response = await client.post(
        f"/api/v1/analyses/{analysis.id}/review",
        json={"action": action},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200, response.text
    assert response.json()["reviews"][0]["comment"] is None


async def test_review_returns_404_for_unknown_analysis(client: AsyncClient) -> None:
    token = await _setup_account(client)
    response = await client.post(
        f"/api/v1/analyses/{uuid.uuid4()}/review",
        json={"action": "validated"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


async def test_review_rejects_invalid_action(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    image, detection = await _make_analyzed_image(db_session)
    analysis = await create_baseline_analysis(db_session, image, [detection])
    await db_session.commit()

    response = await client.post(
        f"/api/v1/analyses/{analysis.id}/review",
        json={"action": "bogus"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_review_requires_authentication(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    image, detection = await _make_analyzed_image(db_session)
    analysis = await create_baseline_analysis(db_session, image, [detection])
    await db_session.commit()

    response = await client.post(
        f"/api/v1/analyses/{analysis.id}/review", json={"action": "validated"}
    )
    assert response.status_code == 401
