from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog

SETUP_PAYLOAD = {
    "email": "operator@pcb-inspect.local",
    "password": "correct-horse-battery",
    "full_name": "Operator One",
}


async def test_setup_status_reports_required_when_no_account(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/setup")
    assert response.status_code == 200
    assert response.json() == {"setup_required": True}


async def test_setup_creates_first_account_and_returns_tokens(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await client.post("/api/v1/auth/setup", json=SETUP_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == SETUP_PAYLOAD["email"]

    entry = await db_session.scalar(select(AuditLog).where(AuditLog.action == "account.created"))
    assert entry is not None
    assert entry.payload is not None
    assert entry.payload["email"] == SETUP_PAYLOAD["email"]


async def test_setup_rejected_once_account_exists(client: AsyncClient) -> None:
    first = await client.post("/api/v1/auth/setup", json=SETUP_PAYLOAD)
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/auth/setup",
        json={**SETUP_PAYLOAD, "email": "someone-else@pcb-inspect.local"},
    )

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "SETUP_ALREADY_COMPLETED"


async def test_setup_status_reports_not_required_once_account_exists(
    client: AsyncClient,
) -> None:
    await client.post("/api/v1/auth/setup", json=SETUP_PAYLOAD)
    status_response = await client.get("/api/v1/auth/setup")

    assert status_response.json() == {"setup_required": False}


async def test_login_with_valid_credentials_returns_tokens(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/setup", json=SETUP_PAYLOAD)

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": SETUP_PAYLOAD["email"], "password": SETUP_PAYLOAD["password"]},
    )

    assert response.status_code == 200
    assert response.json()["user"]["email"] == SETUP_PAYLOAD["email"]


async def test_login_with_invalid_credentials_returns_401(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/setup", json=SETUP_PAYLOAD)

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": SETUP_PAYLOAD["email"], "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_login_with_unknown_email_returns_401(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@pcb-inspect.local", "password": "irrelevant-password"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_refresh_returns_a_working_access_token(client: AsyncClient) -> None:
    setup_response = await client.post("/api/v1/auth/setup", json=SETUP_PAYLOAD)
    refresh_token = setup_response.json()["refresh_token"]

    refresh_response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refresh_response.status_code == 200
    new_access_token = refresh_response.json()["access_token"]

    me_response = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {new_access_token}"}
    )

    assert me_response.status_code == 200
    assert me_response.json()["email"] == SETUP_PAYLOAD["email"]


async def test_refresh_rejects_an_access_token(client: AsyncClient) -> None:
    setup_response = await client.post("/api/v1/auth/setup", json=SETUP_PAYLOAD)
    access_token = setup_response.json()["access_token"]

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": access_token})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


async def test_users_me_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


async def test_login_locks_account_after_repeated_failures(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/setup", json=SETUP_PAYLOAD)

    wrong = {"email": SETUP_PAYLOAD["email"], "password": "definitely-wrong"}
    for _ in range(5):
        await client.post("/api/v1/auth/login", json=wrong)

    locked_response = await client.post(
        "/api/v1/auth/login",
        json={"email": SETUP_PAYLOAD["email"], "password": SETUP_PAYLOAD["password"]},
    )

    assert locked_response.status_code == 423
    assert locked_response.json()["error"]["code"] == "ACCOUNT_LOCKED"
