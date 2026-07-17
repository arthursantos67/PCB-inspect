"""Report request/list/download API (FR-11, FE-07) — router level. Generation itself is
stubbed out here (no Redis broker in the test environment, mirrors every other
`.delay()`-stubbing test in this suite, e.g. `test_model_versions.py`) and exercised for real
in `test_report_generation.py`.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Report
from app.models.enums import ReportFormat, ReportStatus, ReportType
from app.reports import router as reports_router

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


class _FakeGenerateReportTask:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def delay(self, report_id: str) -> None:
        self.calls.append(report_id)


@pytest.fixture(autouse=True)
def _stub_generate_report(monkeypatch: pytest.MonkeyPatch) -> _FakeGenerateReportTask:
    stub = _FakeGenerateReportTask()
    monkeypatch.setattr(reports_router, "generate_report", stub)
    return stub


# --- POST /api/v1/reports -----------------------------------------------------------------


async def test_request_individual_report_queues_and_returns_pending(
    client: AsyncClient, _stub_generate_report: _FakeGenerateReportTask
) -> None:
    token = await _setup_account(client)
    inspection_id = str(uuid.uuid4())

    response = await client.post(
        "/api/v1/reports",
        json={"type": "individual", "format": "pdf", "inspection_id": inspection_id},
        headers=_auth_headers(token),
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["type"] == "individual"
    assert body["format"] == "pdf"
    assert body["status"] == "PENDING"
    assert body["file_path"] is None
    assert body["filters"] == {"inspection_id": inspection_id}
    assert _stub_generate_report.calls == [body["id"]]


async def test_request_consolidated_report_accepts_csv_xlsx_and_pdf(
    client: AsyncClient, _stub_generate_report: _FakeGenerateReportTask
) -> None:
    token = await _setup_account(client)

    for report_format in ("csv", "xlsx", "pdf"):
        response = await client.post(
            "/api/v1/reports",
            json={
                "type": "consolidated",
                "format": report_format,
                "filters": {"batch_number": "BATCH-A"},
            },
            headers=_auth_headers(token),
        )
        assert response.status_code == 202, response.text
        assert response.json()["filters"] == {"batch_number": "BATCH-A"}


async def test_request_consolidated_report_with_no_filters_means_every_inspection(
    client: AsyncClient, _stub_generate_report: _FakeGenerateReportTask
) -> None:
    token = await _setup_account(client)

    response = await client.post(
        "/api/v1/reports",
        json={"type": "consolidated", "format": "csv"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 202, response.text
    assert response.json()["filters"] == {}


async def test_request_executive_report_accepts_a_date_range(
    client: AsyncClient, _stub_generate_report: _FakeGenerateReportTask
) -> None:
    token = await _setup_account(client)

    response = await client.post(
        "/api/v1/reports",
        json={
            "type": "executive",
            "format": "pdf",
            "date_from": "2026-01-01T00:00:00Z",
            "date_to": "2026-01-31T23:59:59Z",
        },
        headers=_auth_headers(token),
    )

    assert response.status_code == 202, response.text
    assert response.json()["filters"] == {
        "date_from": "2026-01-01T00:00:00+00:00",
        "date_to": "2026-01-31T23:59:59+00:00",
    }


async def test_individual_report_rejects_unsupported_format(
    client: AsyncClient, _stub_generate_report: _FakeGenerateReportTask
) -> None:
    token = await _setup_account(client)

    response = await client.post(
        "/api/v1/reports",
        json={"type": "individual", "format": "csv", "inspection_id": str(uuid.uuid4())},
        headers=_auth_headers(token),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert _stub_generate_report.calls == []


async def test_executive_report_rejects_unsupported_format(
    client: AsyncClient, _stub_generate_report: _FakeGenerateReportTask
) -> None:
    token = await _setup_account(client)

    response = await client.post(
        "/api/v1/reports",
        json={"type": "executive", "format": "xlsx"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_individual_report_requires_inspection_id(
    client: AsyncClient, _stub_generate_report: _FakeGenerateReportTask
) -> None:
    token = await _setup_account(client)

    response = await client.post(
        "/api/v1/reports",
        json={"type": "individual", "format": "pdf"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_request_report_requires_authentication(
    client: AsyncClient, _stub_generate_report: _FakeGenerateReportTask
) -> None:
    response = await client.post(
        "/api/v1/reports", json={"type": "executive", "format": "pdf"}
    )

    assert response.status_code == 401
    assert _stub_generate_report.calls == []


# --- GET /api/v1/reports -------------------------------------------------------------------


async def test_list_reports_orders_most_recent_first(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    user_id = uuid.UUID(await _current_user_id(client, token))

    older = Report(
        type=ReportType.EXECUTIVE, format=ReportFormat.PDF, requested_by=user_id
    )
    db_session.add(older)
    await db_session.commit()
    newer = Report(
        type=ReportType.EXECUTIVE, format=ReportFormat.PDF, requested_by=user_id
    )
    db_session.add(newer)
    await db_session.commit()

    response = await client.get("/api/v1/reports", headers=_auth_headers(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 2
    assert [row["id"] for row in body["results"]] == [str(newer.id), str(older.id)]


async def test_list_reports_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/reports")
    assert response.status_code == 401


# --- GET /api/v1/reports/{id}/download -----------------------------------------------------


async def test_download_unknown_report_returns_404(
    client: AsyncClient, _stub_generate_report: _FakeGenerateReportTask
) -> None:
    token = await _setup_account(client)

    response = await client.get(
        f"/api/v1/reports/{uuid.uuid4()}/download", headers=_auth_headers(token)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


async def test_download_pending_report_returns_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    user_id = uuid.UUID(await _current_user_id(client, token))
    report = Report(type=ReportType.EXECUTIVE, format=ReportFormat.PDF, requested_by=user_id)
    db_session.add(report)
    await db_session.commit()

    response = await client.get(
        f"/api/v1/reports/{report.id}/download", headers=_auth_headers(token)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REPORT_NOT_READY"


async def test_download_completed_report_missing_from_disk_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    user_id = uuid.UUID(await _current_user_id(client, token))
    report = Report(
        type=ReportType.EXECUTIVE,
        format=ReportFormat.PDF,
        requested_by=user_id,
        status=ReportStatus.COMPLETED,
        file_path="/tmp/does-not-exist-pcb-inspect-report.pdf",
    )
    db_session.add(report)
    await db_session.commit()

    response = await client.get(
        f"/api/v1/reports/{report.id}/download", headers=_auth_headers(token)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


async def _current_user_id(client: AsyncClient, token: str) -> str:
    response = await client.get("/api/v1/users/me", headers=_auth_headers(token))
    assert response.status_code == 200, response.text
    return response.json()["id"]
