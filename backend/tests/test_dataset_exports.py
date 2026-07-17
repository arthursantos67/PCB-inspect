"""Dataset export request/list/download API (FR-18) — router level. Generation itself is
stubbed out here (no Redis broker in the test environment, mirrors every other `.delay()`-
stubbing test in this suite, e.g. `test_reports.py`) and exercised for real in
`test_dataset_export_generation.py`.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.datasets import router as dataset_exports_router
from app.models import DatasetExport
from app.models.enums import DatasetExportStatus

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


async def _current_user_id(client: AsyncClient, token: str) -> str:
    response = await client.get("/api/v1/users/me", headers=_auth_headers(token))
    assert response.status_code == 200, response.text
    return response.json()["id"]


class _FakeGenerateDatasetExportTask:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def delay(self, export_id: str) -> None:
        self.calls.append(export_id)


@pytest.fixture(autouse=True)
def _stub_generate_dataset_export(
    monkeypatch: pytest.MonkeyPatch,
) -> _FakeGenerateDatasetExportTask:
    stub = _FakeGenerateDatasetExportTask()
    monkeypatch.setattr(dataset_exports_router, "generate_dataset_export", stub)
    return stub


# --- POST /api/v1/dataset-exports ----------------------------------------------------------


async def test_request_dataset_export_with_no_filters_queues_and_returns_pending(
    client: AsyncClient, _stub_generate_dataset_export: _FakeGenerateDatasetExportTask
) -> None:
    token = await _setup_account(client)

    response = await client.post(
        "/api/v1/dataset-exports", json={}, headers=_auth_headers(token)
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["filters"] == {}
    assert body["file_path"] is None
    assert body["manifest"] is None
    assert _stub_generate_dataset_export.calls == [body["id"]]


async def test_request_dataset_export_with_filters_persists_them(
    client: AsyncClient, _stub_generate_dataset_export: _FakeGenerateDatasetExportTask
) -> None:
    token = await _setup_account(client)

    response = await client.post(
        "/api/v1/dataset-exports",
        json={
            "filters": {
                "defect_type": ["short", "spur"],
                "review_status": ["confirmed"],
                "date_from": "2026-01-01T00:00:00Z",
                "date_to": "2026-01-31T23:59:59Z",
            }
        },
        headers=_auth_headers(token),
    )

    assert response.status_code == 202, response.text
    assert response.json()["filters"] == {
        "defect_type": ["short", "spur"],
        "review_status": ["confirmed"],
        "date_from": "2026-01-01T00:00:00Z",
        "date_to": "2026-01-31T23:59:59Z",
    }


async def test_request_dataset_export_with_no_filters_field_means_every_reviewed_detection(
    client: AsyncClient, _stub_generate_dataset_export: _FakeGenerateDatasetExportTask
) -> None:
    token = await _setup_account(client)

    response = await client.post(
        "/api/v1/dataset-exports",
        json={"filters": {}},
        headers=_auth_headers(token),
    )

    assert response.status_code == 202, response.text
    assert response.json()["filters"] == {}


async def test_request_dataset_export_rejects_unreviewed_as_a_filter_value(
    client: AsyncClient, _stub_generate_dataset_export: _FakeGenerateDatasetExportTask
) -> None:
    """`unreviewed` carries no export-worthy signal (FR-18) — same restriction as
    `DetectionFeedbackRequest`.
    """
    token = await _setup_account(client)

    response = await client.post(
        "/api/v1/dataset-exports",
        json={"filters": {"review_status": ["unreviewed"]}},
        headers=_auth_headers(token),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert _stub_generate_dataset_export.calls == []


async def test_request_dataset_export_requires_authentication(
    client: AsyncClient, _stub_generate_dataset_export: _FakeGenerateDatasetExportTask
) -> None:
    response = await client.post("/api/v1/dataset-exports", json={})

    assert response.status_code == 401
    assert _stub_generate_dataset_export.calls == []


# --- GET /api/v1/dataset-exports ------------------------------------------------------------


async def test_list_dataset_exports_orders_most_recent_first(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    user_id = uuid.UUID(await _current_user_id(client, token))

    older = DatasetExport(requested_by=user_id)
    db_session.add(older)
    await db_session.commit()
    newer = DatasetExport(requested_by=user_id)
    db_session.add(newer)
    await db_session.commit()

    response = await client.get("/api/v1/dataset-exports", headers=_auth_headers(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 2
    assert [row["id"] for row in body["results"]] == [str(newer.id), str(older.id)]


async def test_list_dataset_exports_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dataset-exports")
    assert response.status_code == 401


# --- GET /api/v1/dataset-exports/{id}/download ----------------------------------------------


async def test_download_unknown_dataset_export_returns_404(
    client: AsyncClient, _stub_generate_dataset_export: _FakeGenerateDatasetExportTask
) -> None:
    token = await _setup_account(client)

    response = await client.get(
        f"/api/v1/dataset-exports/{uuid.uuid4()}/download", headers=_auth_headers(token)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


async def test_download_pending_dataset_export_returns_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    user_id = uuid.UUID(await _current_user_id(client, token))
    export = DatasetExport(requested_by=user_id)
    db_session.add(export)
    await db_session.commit()

    response = await client.get(
        f"/api/v1/dataset-exports/{export.id}/download", headers=_auth_headers(token)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DATASET_EXPORT_NOT_READY"


async def test_download_completed_dataset_export_missing_from_disk_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    user_id = uuid.UUID(await _current_user_id(client, token))
    export = DatasetExport(
        requested_by=user_id,
        status=DatasetExportStatus.COMPLETED,
        file_path="/tmp/does-not-exist-pcb-inspect-dataset-export.zip",
    )
    db_session.add(export)
    await db_session.commit()

    response = await client.get(
        f"/api/v1/dataset-exports/{export.id}/download", headers=_auth_headers(token)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
