"""Audit trail query API (FR-16) — router level. The write side (`record_audit`) is already
exercised indirectly by every other feature's tests (e.g. `test_alerts.py`,
`test_users.py`); these tests cover only the read side: listing, the account/action/date-range
filters (combinable), pagination, and that a since-removed account's past entries still
resolve an actor.
"""

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.models import AuditLog

FIRST_ACCOUNT = {
    "email": "first@pcb-inspect.local",
    "password": "correct-horse-battery",
    "full_name": "First Operator",
}
SECOND_ACCOUNT = {
    "email": "second@pcb-inspect.local",
    "password": "another-strong-pass",
    "full_name": "Second Operator",
}


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def test_list_audit_log_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/settings/audit")
    assert response.status_code == 401


async def test_list_audit_log_returns_entries_with_actor(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    setup_response = await client.post("/api/v1/auth/setup", json=FIRST_ACCOUNT)
    token = setup_response.json()["access_token"]
    user_id = setup_response.json()["user"]["id"]
    await db_session.commit()

    response = await client.get("/api/v1/settings/audit", headers=_auth_headers(token))

    assert response.status_code == 200, response.text
    body = response.json()
    # Setup itself audits "account.created".
    assert body["count"] == 1
    entry = body["results"][0]
    assert entry["action"] == "account.created"
    assert entry["actor"]["id"] == user_id
    assert entry["actor"]["email"] == FIRST_ACCOUNT["email"]


async def test_list_audit_log_filters_by_account(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    setup_response = await client.post("/api/v1/auth/setup", json=FIRST_ACCOUNT)
    token = setup_response.json()["access_token"]
    first_id = setup_response.json()["user"]["id"]

    create_response = await client.post(
        "/api/v1/users", json=SECOND_ACCOUNT, headers=_auth_headers(token)
    )
    second_id = create_response.json()["id"]
    await db_session.commit()

    first_only = await client.get(
        f"/api/v1/settings/audit?account_id={first_id}", headers=_auth_headers(token)
    )
    second_only = await client.get(
        f"/api/v1/settings/audit?account_id={second_id}", headers=_auth_headers(token)
    )

    # `first_id` performed both creations (its own via setup, and #2's) — the filter is on who
    # performed the action, not who it targeted.
    assert [e["action"] for e in first_only.json()["results"]] == [
        "account.created",
        "account.created",
    ]
    assert second_only.json()["count"] == 0  # nothing yet performed BY #2


async def test_list_audit_log_filters_by_action(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    setup_response = await client.post("/api/v1/auth/setup", json=FIRST_ACCOUNT)
    token = setup_response.json()["access_token"]

    await client.post("/api/v1/auth/login", json=FIRST_ACCOUNT)
    await db_session.commit()

    logins_only = await client.get(
        "/api/v1/settings/audit?action=user.login", headers=_auth_headers(token)
    )
    creations_only = await client.get(
        "/api/v1/settings/audit?action=account.created", headers=_auth_headers(token)
    )

    assert logins_only.json()["count"] == 1
    assert logins_only.json()["results"][0]["action"] == "user.login"
    assert creations_only.json()["count"] == 1
    assert creations_only.json()["results"][0]["action"] == "account.created"


async def test_list_audit_log_filters_by_date_range(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    setup_response = await client.post("/api/v1/auth/setup", json=FIRST_ACCOUNT)
    token = setup_response.json()["access_token"]
    user_id = setup_response.json()["user"]["id"]
    await db_session.commit()

    # audit_log is append-only (RN-06) — an UPDATE after insert is rejected at the DB level,
    # so the backdated row is built directly rather than via `record_audit` + mutate.
    old_entry = AuditLog(
        actor_id=uuid.UUID(user_id),
        action="config.updated",
        entity_type="system_config",
        payload={"key": "min_confidence_report"},
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    db_session.add(old_entry)
    await db_session.commit()

    in_range = await client.get(
        "/api/v1/settings/audit?date_from=2025-01-01T00:00:00Z",
        headers=_auth_headers(token),
    )
    out_of_range = await client.get(
        "/api/v1/settings/audit?date_from=2020-01-01T00:00:00Z&date_to=2020-12-31T23:59:59Z",
        headers=_auth_headers(token),
    )

    assert [e["action"] for e in in_range.json()["results"]] == ["account.created"]
    assert [e["action"] for e in out_of_range.json()["results"]] == ["config.updated"]


async def test_list_audit_log_filters_are_combinable(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    setup_response = await client.post("/api/v1/auth/setup", json=FIRST_ACCOUNT)
    token = setup_response.json()["access_token"]
    first_id = setup_response.json()["user"]["id"]

    create_response = await client.post(
        "/api/v1/users", json=SECOND_ACCOUNT, headers=_auth_headers(token)
    )
    second_id = create_response.json()["id"]
    await client.patch(
        f"/api/v1/users/{second_id}",
        json={"full_name": "Renamed Operator"},
        headers=_auth_headers(token),
    )
    await db_session.commit()

    # first_id performed the rename too (acting on second_id's account) — combining its
    # account_id with the "account.updated" action narrows to exactly that one entry.
    response = await client.get(
        f"/api/v1/settings/audit?account_id={first_id}&action=account.updated",
        headers=_auth_headers(token),
    )
    assert response.json()["count"] == 1

    response = await client.get(
        f"/api/v1/settings/audit?account_id={first_id}&action=account.created",
        headers=_auth_headers(token),
    )
    assert response.json()["count"] == 2  # first_id created itself and second_id

    response = await client.get(
        f"/api/v1/settings/audit?account_id={second_id}&action=account.updated",
        headers=_auth_headers(token),
    )
    assert response.json()["count"] == 0  # #2 didn't perform the rename, it was the target


async def test_list_audit_log_resolves_actor_for_removed_account(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    setup_response = await client.post("/api/v1/auth/setup", json=FIRST_ACCOUNT)
    token = setup_response.json()["access_token"]

    create_response = await client.post(
        "/api/v1/users", json=SECOND_ACCOUNT, headers=_auth_headers(token)
    )
    second_id = create_response.json()["id"]
    await client.delete(f"/api/v1/users/{second_id}", headers=_auth_headers(token))
    await db_session.commit()

    response = await client.get(
        "/api/v1/settings/audit?action=account.removed", headers=_auth_headers(token)
    )

    assert response.json()["count"] == 1
    entry = response.json()["results"][0]
    assert entry["entity_id"] == second_id
    # The actor is the account that performed the removal (still active), not the removed one.
    assert entry["actor"]["email"] == FIRST_ACCOUNT["email"]


async def test_list_audit_log_paginates(client: AsyncClient, db_session: AsyncSession) -> None:
    setup_response = await client.post("/api/v1/auth/setup", json=FIRST_ACCOUNT)
    token = setup_response.json()["access_token"]
    user_id = setup_response.json()["user"]["id"]

    for i in range(3):
        await record_audit(
            db_session,
            actor_id=uuid.UUID(user_id),
            action="config.updated",
            entity_type="system_config",
            payload={"key": f"setting_{i}"},
        )
    await db_session.commit()

    # 1 "account.created" from setup + 3 "config.updated" = 4 total.
    first_page = await client.get(
        "/api/v1/settings/audit?page=1&page_size=2", headers=_auth_headers(token)
    )
    second_page = await client.get(
        "/api/v1/settings/audit?page=2&page_size=2", headers=_auth_headers(token)
    )

    assert first_page.json()["count"] == 4
    assert len(first_page.json()["results"]) == 2
    assert first_page.json()["previous"] is None
    assert first_page.json()["next"] is not None
    assert len(second_page.json()["results"]) == 2
    assert second_page.json()["previous"] is not None
