from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def test_list_users_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users")
    assert response.status_code == 401


async def test_authenticated_account_can_list_add_rename_and_remove_others(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    setup_response = await client.post("/api/v1/auth/setup", json=FIRST_ACCOUNT)
    first_token = setup_response.json()["access_token"]

    create_response = await client.post(
        "/api/v1/users", json=SECOND_ACCOUNT, headers=_auth_headers(first_token)
    )
    assert create_response.status_code == 201
    second_id = create_response.json()["id"]

    list_response = await client.get("/api/v1/users", headers=_auth_headers(first_token))
    assert list_response.status_code == 200
    emails = {user["email"] for user in list_response.json()}
    assert emails == {FIRST_ACCOUNT["email"], SECOND_ACCOUNT["email"]}

    # No role gating: the second (freshly created) account can manage the first one too.
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": SECOND_ACCOUNT["email"], "password": SECOND_ACCOUNT["password"]},
    )
    second_token = login_response.json()["access_token"]

    rename_response = await client.patch(
        f"/api/v1/users/{second_id}",
        json={"full_name": "Renamed Operator"},
        headers=_auth_headers(second_token),
    )
    assert rename_response.status_code == 200
    assert rename_response.json()["full_name"] == "Renamed Operator"

    delete_response = await client.delete(
        f"/api/v1/users/{second_id}", headers=_auth_headers(first_token)
    )
    assert delete_response.status_code == 204

    list_after_delete = await client.get("/api/v1/users", headers=_auth_headers(first_token))
    remaining_emails = {user["email"] for user in list_after_delete.json()}
    assert remaining_emails == {FIRST_ACCOUNT["email"]}

    updated_entry = await db_session.scalar(
        select(AuditLog).where(AuditLog.action == "account.updated")
    )
    assert updated_entry is not None
    removed_entry = await db_session.scalar(
        select(AuditLog).where(AuditLog.action == "account.removed")
    )
    assert removed_entry is not None


async def test_removed_account_can_no_longer_log_in(client: AsyncClient) -> None:
    setup_response = await client.post("/api/v1/auth/setup", json=FIRST_ACCOUNT)
    first_token = setup_response.json()["access_token"]

    create_response = await client.post(
        "/api/v1/users", json=SECOND_ACCOUNT, headers=_auth_headers(first_token)
    )
    second_id = create_response.json()["id"]

    await client.delete(f"/api/v1/users/{second_id}", headers=_auth_headers(first_token))

    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": SECOND_ACCOUNT["email"], "password": SECOND_ACCOUNT["password"]},
    )

    assert login_response.status_code == 401
    assert login_response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_cannot_delete_the_last_remaining_account(client: AsyncClient) -> None:
    setup_response = await client.post("/api/v1/auth/setup", json=FIRST_ACCOUNT)
    token = setup_response.json()["access_token"]
    user_id = setup_response.json()["user"]["id"]

    response = await client.delete(f"/api/v1/users/{user_id}", headers=_auth_headers(token))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CANNOT_DELETE_LAST_ACCOUNT"


async def test_create_user_rejects_duplicate_email(client: AsyncClient) -> None:
    setup_response = await client.post("/api/v1/auth/setup", json=FIRST_ACCOUNT)
    token = setup_response.json()["access_token"]

    response = await client.post(
        "/api/v1/users",
        json={**SECOND_ACCOUNT, "email": FIRST_ACCOUNT["email"]},
        headers=_auth_headers(token),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_create_user_rejects_short_password(client: AsyncClient) -> None:
    setup_response = await client.post("/api/v1/auth/setup", json=FIRST_ACCOUNT)
    token = setup_response.json()["access_token"]

    response = await client.post(
        "/api/v1/users",
        json={**SECOND_ACCOUNT, "password": "short"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
