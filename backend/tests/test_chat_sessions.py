"""`/api/v1/chat/sessions` CRUD (FR-09, PRD section 11.2) — creation (including
context-scoped sessions, FE-03), listing, detail retrieval, deletion, and the ownership check
(PRD section 13: "the only per-resource check is ownership for private data like chat
sessions").
"""

import uuid
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyses.service import create_baseline_analysis
from app.models import Detection, InspectionImage, ModelVersion
from app.models.enums import DefectType, ImageSource, ImageStatus

ACCOUNT = {
    "email": "operator@pcb-inspect.local",
    "password": "correct-horse-battery",
    "full_name": "Operator",
}
OTHER_ACCOUNT_CREATE = {
    "email": "other@pcb-inspect.local",
    "password": "another-horse-battery",
    "full_name": "Other Operator",
}


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _setup_account(client: AsyncClient) -> str:
    response = await client.post("/api/v1/auth/setup", json=ACCOUNT)
    return response.json()["access_token"]


async def _create_second_account_token(client: AsyncClient, first_account_token: str) -> str:
    await client.post(
        "/api/v1/users", json=OTHER_ACCOUNT_CREATE, headers=_auth_headers(first_account_token)
    )
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": OTHER_ACCOUNT_CREATE["email"], "password": OTHER_ACCOUNT_CREATE["password"]},
    )
    return response.json()["access_token"]


async def _make_analysis(db_session: AsyncSession) -> uuid.UUID:
    model_version = ModelVersion(version="v1.0.0", weights_path="/weights/best.pt", is_active=True)
    db_session.add(model_version)
    await db_session.flush()
    image = InspectionImage(
        source=ImageSource.WATCH_FOLDER,
        original_path="/tmp/board.jpg",
        checksum_sha256=uuid.uuid4().hex,
        status=ImageStatus.DETECTED,
    )
    db_session.add(image)
    await db_session.flush()
    detection = Detection(
        image_id=image.id,
        defect_type=DefectType.SHORT,
        bbox={"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4},
        confidence=Decimal("0.900"),
        is_reported=True,
        model_version_id=model_version.id,
    )
    db_session.add(detection)
    await db_session.flush()
    analysis = await create_baseline_analysis(db_session, image, [detection])
    await db_session.commit()
    return analysis.id


async def test_create_session_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/api/v1/chat/sessions", json={})
    assert response.status_code == 401


async def test_create_session_without_context(client: AsyncClient) -> None:
    token = await _setup_account(client)

    response = await client.post(
        "/api/v1/chat/sessions", json={}, headers=_auth_headers(token)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] is None
    assert body["context_analysis_id"] is None
    assert "id" in body


async def test_create_session_scoped_to_an_analysis(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    analysis_id = await _make_analysis(db_session)

    response = await client.post(
        "/api/v1/chat/sessions",
        json={"context_analysis_id": str(analysis_id)},
        headers=_auth_headers(token),
    )

    assert response.status_code == 201
    assert response.json()["context_analysis_id"] == str(analysis_id)


async def test_create_session_with_unknown_context_analysis_returns_404(
    client: AsyncClient,
) -> None:
    token = await _setup_account(client)

    response = await client.post(
        "/api/v1/chat/sessions",
        json={"context_analysis_id": str(uuid.uuid4())},
        headers=_auth_headers(token),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


async def test_list_sessions_returns_only_the_caller_s_own_sessions(client: AsyncClient) -> None:
    token = await _setup_account(client)
    other_token = await _create_second_account_token(client, token)

    await client.post("/api/v1/chat/sessions", json={}, headers=_auth_headers(token))
    await client.post("/api/v1/chat/sessions", json={}, headers=_auth_headers(other_token))

    response = await client.get("/api/v1/chat/sessions", headers=_auth_headers(token))

    assert response.status_code == 200
    assert len(response.json()["results"]) == 1


async def test_get_session_detail_includes_messages(client: AsyncClient) -> None:
    token = await _setup_account(client)
    create_response = await client.post(
        "/api/v1/chat/sessions", json={}, headers=_auth_headers(token)
    )
    session_id = create_response.json()["id"]

    response = await client.get(
        f"/api/v1/chat/sessions/{session_id}", headers=_auth_headers(token)
    )

    assert response.status_code == 200
    assert response.json()["messages"] == []


async def test_get_session_owned_by_another_account_is_forbidden(client: AsyncClient) -> None:
    token = await _setup_account(client)
    other_token = await _create_second_account_token(client, token)
    create_response = await client.post(
        "/api/v1/chat/sessions", json={}, headers=_auth_headers(token)
    )
    session_id = create_response.json()["id"]

    response = await client.get(
        f"/api/v1/chat/sessions/{session_id}", headers=_auth_headers(other_token)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_get_unknown_session_returns_404(client: AsyncClient) -> None:
    token = await _setup_account(client)

    response = await client.get(
        f"/api/v1/chat/sessions/{uuid.uuid4()}", headers=_auth_headers(token)
    )

    assert response.status_code == 404


async def test_delete_session_removes_it(client: AsyncClient) -> None:
    token = await _setup_account(client)
    create_response = await client.post(
        "/api/v1/chat/sessions", json={}, headers=_auth_headers(token)
    )
    session_id = create_response.json()["id"]

    delete_response = await client.delete(
        f"/api/v1/chat/sessions/{session_id}", headers=_auth_headers(token)
    )
    assert delete_response.status_code == 204

    get_response = await client.get(
        f"/api/v1/chat/sessions/{session_id}", headers=_auth_headers(token)
    )
    assert get_response.status_code == 404


async def test_delete_session_owned_by_another_account_is_forbidden(client: AsyncClient) -> None:
    token = await _setup_account(client)
    other_token = await _create_second_account_token(client, token)
    create_response = await client.post(
        "/api/v1/chat/sessions", json={}, headers=_auth_headers(token)
    )
    session_id = create_response.json()["id"]

    response = await client.delete(
        f"/api/v1/chat/sessions/{session_id}", headers=_auth_headers(other_token)
    )

    assert response.status_code == 403
