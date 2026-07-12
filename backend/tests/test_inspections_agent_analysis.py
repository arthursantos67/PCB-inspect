"""`POST /api/v1/inspections/{id}/agent-analysis` (FE-03, `on_demand` mode, issue #31) — the
explicit trigger the analysis detail screen calls to request the Analyst/Reviewer/Summarizer
chain on demand.
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyses.service import create_baseline_analysis
from app.inspections import router as inspections_router
from app.models import Detection, InspectionImage, ModelVersion
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


async def _make_completed_inspection_with_baseline(db: AsyncSession) -> InspectionImage:
    model_version = await _make_model_version(db)
    image = InspectionImage(
        source=ImageSource.WATCH_FOLDER,
        original_path="/tmp/board.jpg",
        checksum_sha256=uuid.uuid4().hex,
        status=ImageStatus.DETECTED,
    )
    db.add(image)
    await db.flush()
    detection = Detection(
        image_id=image.id,
        defect_type=DefectType.SHORT,
        bbox={"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4},
        confidence=Decimal("0.900"),
        is_reported=True,
        model_version_id=model_version.id,
    )
    db.add(detection)
    await db.flush()
    await create_baseline_analysis(db, image, [detection])  # transitions DETECTED -> COMPLETED
    await db.commit()
    return image


class _FakeAgentAnalysisTask:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def delay(self, inspection_image_id: str) -> None:
        self.calls.append(inspection_image_id)


@pytest.fixture(autouse=True)
def _stub_agent_enqueue(monkeypatch: pytest.MonkeyPatch) -> _FakeAgentAnalysisTask:
    """No Redis broker in the test environment — mirrors how ingestion tests stub
    `run_inference`'s own enqueue call.
    """
    stub = _FakeAgentAnalysisTask()
    monkeypatch.setattr(inspections_router, "run_agent_analysis", stub)
    return stub


async def test_request_agent_analysis_queues_and_transitions_to_analyzing(
    client: AsyncClient, db_session: AsyncSession, _stub_agent_enqueue: _FakeAgentAnalysisTask
) -> None:
    token = await _setup_account(client)
    image = await _make_completed_inspection_with_baseline(db_session)

    response = await client.post(
        f"/api/v1/inspections/{image.id}/agent-analysis", headers=_auth_headers(token)
    )

    assert response.status_code == 202
    assert response.json() == {"status": "queued"}
    assert _stub_agent_enqueue.calls == [str(image.id)]

    await db_session.refresh(image)
    assert image.status == ImageStatus.ANALYZING


async def test_request_agent_analysis_returns_404_for_unknown_inspection(
    client: AsyncClient, _stub_agent_enqueue: _FakeAgentAnalysisTask
) -> None:
    token = await _setup_account(client)

    response = await client.post(
        f"/api/v1/inspections/{uuid.uuid4()}/agent-analysis", headers=_auth_headers(token)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INSPECTION_NOT_FOUND"
    assert _stub_agent_enqueue.calls == []


async def test_request_agent_analysis_requires_a_baseline_analysis(
    client: AsyncClient, db_session: AsyncSession, _stub_agent_enqueue: _FakeAgentAnalysisTask
) -> None:
    token = await _setup_account(client)
    image = InspectionImage(
        source=ImageSource.WATCH_FOLDER,
        original_path="/tmp/board.jpg",
        checksum_sha256=uuid.uuid4().hex,
        status=ImageStatus.QUEUED,
    )
    db_session.add(image)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/inspections/{image.id}/agent-analysis", headers=_auth_headers(token)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INSPECTION_NOT_READY"
    assert _stub_agent_enqueue.calls == []


async def test_request_agent_analysis_rejects_when_inspection_is_not_completed(
    client: AsyncClient, db_session: AsyncSession, _stub_agent_enqueue: _FakeAgentAnalysisTask
) -> None:
    """A baseline analysis exists but the image itself is still mid-pipeline — the state
    machine (COMPLETED -> ANALYZING only) rejects the request rather than corrupting the
    in-flight pipeline run.
    """
    token = await _setup_account(client)
    image = await _make_completed_inspection_with_baseline(db_session)
    image.status = ImageStatus.PROCESSING
    await db_session.commit()

    response = await client.post(
        f"/api/v1/inspections/{image.id}/agent-analysis", headers=_auth_headers(token)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INSPECTION_NOT_READY"
    assert _stub_agent_enqueue.calls == []


async def test_request_agent_analysis_requires_authentication(
    client: AsyncClient, db_session: AsyncSession, _stub_agent_enqueue: _FakeAgentAnalysisTask
) -> None:
    image = await _make_completed_inspection_with_baseline(db_session)

    response = await client.post(f"/api/v1/inspections/{image.id}/agent-analysis")

    assert response.status_code == 401
    assert _stub_agent_enqueue.calls == []
