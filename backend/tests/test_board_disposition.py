"""POST /api/v1/inspections/{id}/disposition (FR-10, UC-5, Issue 33) — recording a board's
final disposition, one row per inspection (RN-09), audited per FR-16, and surfaced on the
detail screen and search results (Issue 8's `disposition` filter).
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, InspectionImage
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


async def test_set_disposition_persists_decision_and_actor(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    image = await _make_image(db_session)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/inspections/{image.id}/disposition",
        json={"decision": "approved"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"] == "approved"
    assert body["image_id"] == str(image.id)
    assert body["decided_by"] is not None


async def test_disposition_shows_on_detail_screen(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    image = await _make_image(db_session)
    await db_session.commit()

    await client.post(
        f"/api/v1/inspections/{image.id}/disposition",
        json={"decision": "rework"},
        headers=_auth_headers(token),
    )

    detail = await client.get(
        f"/api/v1/inspections/{image.id}", headers=_auth_headers(token)
    )
    assert detail.status_code == 200
    assert detail.json()["disposition"]["decision"] == "rework"


async def test_disposition_shows_on_search_results(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    image = await _make_image(db_session)
    await db_session.commit()

    await client.post(
        f"/api/v1/inspections/{image.id}/disposition",
        json={"decision": "discarded"},
        headers=_auth_headers(token),
    )

    listing = await client.get("/api/v1/inspections", headers=_auth_headers(token))
    assert listing.status_code == 200
    row = next(r for r in listing.json()["results"] if r["id"] == str(image.id))
    assert row["disposition"] == "discarded"


async def test_changing_disposition_updates_in_place_and_keeps_one_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    image = await _make_image(db_session)
    await db_session.commit()

    await client.post(
        f"/api/v1/inspections/{image.id}/disposition",
        json={"decision": "approved"},
        headers=_auth_headers(token),
    )
    second = await client.post(
        f"/api/v1/inspections/{image.id}/disposition",
        json={"decision": "discarded"},
        headers=_auth_headers(token),
    )

    assert second.status_code == 200
    assert second.json()["decision"] == "discarded"

    from app.models import BoardDisposition

    rows = (
        await db_session.scalars(
            select(BoardDisposition).where(BoardDisposition.image_id == image.id)
        )
    ).all()
    assert len(rows) == 1  # RN-09: one disposition per inspection, updated in place
    assert rows[0].decision.value == "discarded"


async def test_disposition_produces_audit_log_with_previous_value(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    image = await _make_image(db_session)
    await db_session.commit()

    await client.post(
        f"/api/v1/inspections/{image.id}/disposition",
        json={"decision": "approved"},
        headers=_auth_headers(token),
    )
    await client.post(
        f"/api/v1/inspections/{image.id}/disposition",
        json={"decision": "rework"},
        headers=_auth_headers(token),
    )

    entries = (
        await db_session.scalars(
            select(AuditLog)
            .where(AuditLog.entity_type == "board_disposition")
            .order_by(AuditLog.id)
        )
    ).all()
    assert len(entries) == 2
    assert entries[0].payload == {"decision": "approved", "previous": None}
    assert entries[1].payload == {"decision": "rework", "previous": "approved"}


async def test_disposition_returns_404_for_unknown_inspection(client: AsyncClient) -> None:
    token = await _setup_account(client)
    response = await client.post(
        f"/api/v1/inspections/{uuid.uuid4()}/disposition",
        json={"decision": "approved"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INSPECTION_NOT_FOUND"


async def test_disposition_rejects_invalid_decision(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    image = await _make_image(db_session)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/inspections/{image.id}/disposition",
        json={"decision": "bogus"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_disposition_requires_authentication(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    image = await _make_image(db_session)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/inspections/{image.id}/disposition", json={"decision": "approved"}
    )
    assert response.status_code == 401
