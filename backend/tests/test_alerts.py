"""Alert list/acknowledge API (FR-19) — router level. Threshold evaluation itself is exercised
in `test_alert_monitoring.py`; these tests seed `QualityAlert` rows directly so they only cover
the API surface: listing (with the `acknowledged` filter), acknowledging (audited, FR-16), and
the "already acknowledged"/"not found" edge cases.
"""

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, QualityAlert
from app.models.enums import QualityAlertType

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


async def _make_alert(
    db: AsyncSession,
    *,
    type_: QualityAlertType = QualityAlertType.DEFECT_RATE_BATCH,
    scope_key: str = "scope-1",
    observed_rate: float = 0.42,
    threshold: float = 0.15,
    created_at: datetime | None = None,
) -> QualityAlert:
    alert = QualityAlert(
        type=type_,
        scope_key=scope_key,
        context={"observed_rate": observed_rate, "threshold": threshold},
    )
    if created_at is not None:
        alert.created_at = created_at
    db.add(alert)
    await db.flush()
    return alert


# --- GET /api/v1/alerts ----------------------------------------------------------------------


async def test_list_alerts_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/alerts")
    assert response.status_code == 401


async def test_list_alerts_returns_every_alert_with_computed_status(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    active = await _make_alert(db_session, scope_key="batch-1")
    await db_session.commit()

    response = await client.get("/api/v1/alerts", headers=_auth_headers(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 1
    result = body["results"][0]
    assert result["id"] == str(active.id)
    assert result["status"] == "active"
    assert result["type"] == "defect_rate_batch"
    assert result["context"]["observed_rate"] == 0.42
    assert result["acknowledged_by"] is None
    assert result["acknowledged_at"] is None


async def test_list_alerts_filters_by_acknowledged(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    active = await _make_alert(db_session, scope_key="batch-1")
    acked = await _make_alert(db_session, scope_key="batch-2")
    await db_session.commit()

    ack_response = await client.post(
        f"/api/v1/alerts/{acked.id}/ack", headers=_auth_headers(token)
    )
    assert ack_response.status_code == 200, ack_response.text

    active_only = await client.get(
        "/api/v1/alerts?acknowledged=false", headers=_auth_headers(token)
    )
    acked_only = await client.get(
        "/api/v1/alerts?acknowledged=true", headers=_auth_headers(token)
    )

    assert [r["id"] for r in active_only.json()["results"]] == [str(active.id)]
    assert [r["id"] for r in acked_only.json()["results"]] == [str(acked.id)]


async def test_list_alerts_orders_most_recent_first(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    first = await _make_alert(
        db_session, scope_key="batch-1", created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    second = await _make_alert(
        db_session, scope_key="batch-2", created_at=datetime(2026, 1, 2, tzinfo=UTC)
    )
    await db_session.commit()

    response = await client.get("/api/v1/alerts", headers=_auth_headers(token))

    ids = [r["id"] for r in response.json()["results"]]
    assert ids == [str(second.id), str(first.id)]


# --- POST /api/v1/alerts/{id}/ack ---------------------------------------------------------


async def test_acknowledge_alert_clears_it_and_records_actor(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    user_response = await client.get("/api/v1/users/me", headers=_auth_headers(token))
    user_id = user_response.json()["id"]
    alert = await _make_alert(db_session)
    await db_session.commit()

    response = await client.post(f"/api/v1/alerts/{alert.id}/ack", headers=_auth_headers(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "acknowledged"
    assert body["acknowledged_by"] == user_id
    assert body["acknowledged_at"] is not None


async def test_acknowledge_alert_produces_audit_log_entry(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    alert = await _make_alert(db_session)
    await db_session.commit()

    response = await client.post(f"/api/v1/alerts/{alert.id}/ack", headers=_auth_headers(token))
    assert response.status_code == 200, response.text

    entries = (
        await db_session.scalars(
            select(AuditLog).where(
                AuditLog.entity_type == "quality_alert", AuditLog.entity_id == alert.id
            )
        )
    ).all()
    assert len(entries) == 1
    assert entries[0].action == "alert.acknowledged"
    assert entries[0].actor_id is not None


async def test_acknowledge_already_acknowledged_alert_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    alert = await _make_alert(db_session)
    await db_session.commit()

    first = await client.post(f"/api/v1/alerts/{alert.id}/ack", headers=_auth_headers(token))
    assert first.status_code == 200

    second = await client.post(f"/api/v1/alerts/{alert.id}/ack", headers=_auth_headers(token))

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "ALERT_ALREADY_ACKNOWLEDGED"


async def test_acknowledge_unknown_alert_returns_404(client: AsyncClient) -> None:
    token = await _setup_account(client)

    response = await client.post(
        f"/api/v1/alerts/{uuid.uuid4()}/ack", headers=_auth_headers(token)
    )

    assert response.status_code == 404


async def test_acknowledge_requires_auth(client: AsyncClient) -> None:
    response = await client.post(f"/api/v1/alerts/{uuid.uuid4()}/ack")
    assert response.status_code == 401
