"""Model version registration and the activation gate (FR-12, NFR-05, RN-02, RN-10) — API
level. The golden-set evaluation task itself is stubbed out here (no Redis broker in the test
environment, mirrors every other `.delay()`-stubbing test in this suite) and exercised for
real in `test_model_evaluation_task.py`.
"""

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, ModelVersion
from app.models.enums import ModelEvaluationStatus
from app.settings import models_router

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


class _FakeTask:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def delay(self, *args: object) -> None:
        self.calls.append(args)


@pytest.fixture(autouse=True)
def _stub_tasks(monkeypatch: pytest.MonkeyPatch) -> dict[str, _FakeTask]:
    """No Redis broker in the test environment — mirrors how ingestion/agent-analysis tests
    stub their own `.delay()` enqueue calls.
    """
    evaluation = _FakeTask()
    reload = _FakeTask()
    monkeypatch.setattr(models_router, "run_model_evaluation", evaluation)
    monkeypatch.setattr(models_router, "reload_inference_model", reload)
    return {"evaluation": evaluation, "reload": reload}


def _weights_file(tmp_path: Path, name: str = "candidate.pt") -> Path:
    path = tmp_path / name
    path.write_bytes(b"not-real-weights")
    return path


async def _set_evaluation(
    db_session: AsyncSession,
    model_version_id: object,
    *,
    status: ModelEvaluationStatus,
    map50: float | None = None,
) -> None:
    model_version = await db_session.get(ModelVersion, model_version_id)
    assert model_version is not None
    model_version.evaluation_status = status
    if map50 is not None:
        model_version.metrics = {"map50": map50, "map50_95": map50, "per_class": {}}
    await db_session.commit()


# --- Registration (FR-12, RN-10) ----------------------------------------------------------


async def test_register_model_version_is_pending_with_no_metrics_and_triggers_evaluation(
    client: AsyncClient, tmp_path: Path, _stub_tasks: dict[str, _FakeTask]
) -> None:
    token = await _setup_account(client)
    weights = _weights_file(tmp_path)

    response = await client.post(
        "/api/v1/settings/models",
        json={"version": "v1.1.0", "weights_path": str(weights)},
        headers=_auth_headers(token),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["version"] == "v1.1.0"
    assert body["evaluation_status"] == "PENDING"
    assert body["metrics"] is None
    assert body["is_active"] is False
    assert len(_stub_tasks["evaluation"].calls) == 1
    assert _stub_tasks["evaluation"].calls[0] == (body["id"],)


async def test_register_ignores_a_metrics_field_in_the_payload(
    client: AsyncClient, tmp_path: Path
) -> None:
    """RN-10 / "Evaluation Is Real": there is no way to set `metrics` except the evaluation
    task actually running — an extra `metrics` key in the request body is simply not part of
    the accepted schema and must never round-trip.
    """
    token = await _setup_account(client)
    weights = _weights_file(tmp_path)

    response = await client.post(
        "/api/v1/settings/models",
        json={
            "version": "v1.2.0",
            "weights_path": str(weights),
            "metrics": {"map50": 0.99, "map50_95": 0.99, "per_class": {}},
        },
        headers=_auth_headers(token),
    )

    assert response.status_code == 201
    assert response.json()["metrics"] is None


async def test_register_duplicate_version_is_rejected(
    client: AsyncClient, tmp_path: Path
) -> None:
    token = await _setup_account(client)
    weights = _weights_file(tmp_path)
    await client.post(
        "/api/v1/settings/models",
        json={"version": "v2.0.0", "weights_path": str(weights)},
        headers=_auth_headers(token),
    )

    response = await client.post(
        "/api/v1/settings/models",
        json={"version": "v2.0.0", "weights_path": str(weights)},
        headers=_auth_headers(token),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODEL_VERSION_EXISTS"


async def test_register_missing_weights_file_is_rejected(
    client: AsyncClient, tmp_path: Path, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)

    response = await client.post(
        "/api/v1/settings/models",
        json={"version": "v3.0.0", "weights_path": str(tmp_path / "nope.pt")},
        headers=_auth_headers(token),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PATH_NOT_FOUND"
    assert (
        await db_session.scalar(select(func.count()).select_from(ModelVersion))
    ) == 0


async def test_list_model_versions_returns_every_registered_version(
    client: AsyncClient, tmp_path: Path
) -> None:
    token = await _setup_account(client)
    for name in ("v4.0.0", "v4.0.1"):
        await client.post(
            "/api/v1/settings/models",
            json={"version": name, "weights_path": str(_weights_file(tmp_path, f"{name}.pt"))},
            headers=_auth_headers(token),
        )

    response = await client.get("/api/v1/settings/models", headers=_auth_headers(token))

    assert response.status_code == 200
    versions = {row["version"] for row in response.json()}
    assert {"v4.0.0", "v4.0.1"} <= versions


async def test_get_evaluation_reflects_current_status(
    client: AsyncClient, tmp_path: Path, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    register = await client.post(
        "/api/v1/settings/models",
        json={"version": "v5.0.0", "weights_path": str(_weights_file(tmp_path))},
        headers=_auth_headers(token),
    )
    model_version_id = register.json()["id"]
    await _set_evaluation(
        db_session, model_version_id, status=ModelEvaluationStatus.COMPLETED, map50=0.97
    )

    response = await client.get(
        f"/api/v1/settings/models/{model_version_id}/evaluation", headers=_auth_headers(token)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["evaluation_status"] == "COMPLETED"
    assert body["metrics"]["map50"] == 0.97


# --- Activation gate (FR-12, NFR-05) -------------------------------------------------------


async def test_activate_is_blocked_while_evaluation_is_pending(
    client: AsyncClient, tmp_path: Path
) -> None:
    token = await _setup_account(client)
    register = await client.post(
        "/api/v1/settings/models",
        json={"version": "v6.0.0", "weights_path": str(_weights_file(tmp_path))},
        headers=_auth_headers(token),
    )
    model_version_id = register.json()["id"]

    response = await client.post(
        f"/api/v1/settings/models/{model_version_id}/activate",
        json={},
        headers=_auth_headers(token),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MODEL_ACTIVATION_FAILED"


async def test_activate_is_blocked_below_the_map50_floor_without_override(
    client: AsyncClient, tmp_path: Path, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    register = await client.post(
        "/api/v1/settings/models",
        json={"version": "v7.0.0", "weights_path": str(_weights_file(tmp_path))},
        headers=_auth_headers(token),
    )
    model_version_id = register.json()["id"]
    await _set_evaluation(
        db_session, model_version_id, status=ModelEvaluationStatus.COMPLETED, map50=0.80
    )

    response = await client.post(
        f"/api/v1/settings/models/{model_version_id}/activate",
        json={},
        headers=_auth_headers(token),
    )

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "MODEL_ACTIVATION_FAILED"
    assert body["details"]["map50"] == 0.80
    assert body["details"]["floor"] == 0.95


async def test_activate_override_without_justification_is_rejected(
    client: AsyncClient, tmp_path: Path, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    register = await client.post(
        "/api/v1/settings/models",
        json={"version": "v8.0.0", "weights_path": str(_weights_file(tmp_path))},
        headers=_auth_headers(token),
    )
    model_version_id = register.json()["id"]
    await _set_evaluation(
        db_session, model_version_id, status=ModelEvaluationStatus.COMPLETED, map50=0.80
    )

    response = await client.post(
        f"/api/v1/settings/models/{model_version_id}/activate",
        json={"override": True},
        headers=_auth_headers(token),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_activate_override_with_justification_succeeds_and_is_audited(
    client: AsyncClient,
    tmp_path: Path,
    db_session: AsyncSession,
    _stub_tasks: dict[str, _FakeTask],
) -> None:
    token = await _setup_account(client)
    register = await client.post(
        "/api/v1/settings/models",
        json={"version": "v9.0.0", "weights_path": str(_weights_file(tmp_path))},
        headers=_auth_headers(token),
    )
    model_version_id = register.json()["id"]
    await _set_evaluation(
        db_session, model_version_id, status=ModelEvaluationStatus.COMPLETED, map50=0.80
    )

    response = await client.post(
        f"/api/v1/settings/models/{model_version_id}/activate",
        json={"override": True, "justification": "Domain-shifted golden set, approved by QA."},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_active"] is True
    assert body["activated_at"] is not None
    assert len(_stub_tasks["reload"].calls) == 1

    audit = await db_session.scalar(
        select(AuditLog).where(AuditLog.action == "model.activated")
    )
    assert audit is not None
    assert audit.payload["override"] is True
    assert audit.payload["justification"] == "Domain-shifted golden set, approved by QA."


async def test_activate_above_the_floor_deactivates_the_previous_version(
    client: AsyncClient, tmp_path: Path, db_session: AsyncSession
) -> None:
    """RN-02 is exercised by this flow, not bypassed: activating a second version must leave
    exactly one `is_active=true` row, enforced by the real partial unique index.
    """
    token = await _setup_account(client)

    first = await client.post(
        "/api/v1/settings/models",
        json={"version": "v10.0.0", "weights_path": str(_weights_file(tmp_path, "a.pt"))},
        headers=_auth_headers(token),
    )
    first_id = first.json()["id"]
    await _set_evaluation(
        db_session, first_id, status=ModelEvaluationStatus.COMPLETED, map50=0.98
    )
    activate_first = await client.post(
        f"/api/v1/settings/models/{first_id}/activate", json={}, headers=_auth_headers(token)
    )
    assert activate_first.status_code == 200

    second = await client.post(
        "/api/v1/settings/models",
        json={"version": "v10.0.1", "weights_path": str(_weights_file(tmp_path, "b.pt"))},
        headers=_auth_headers(token),
    )
    second_id = second.json()["id"]
    await _set_evaluation(
        db_session, second_id, status=ModelEvaluationStatus.COMPLETED, map50=0.99
    )
    activate_second = await client.post(
        f"/api/v1/settings/models/{second_id}/activate", json={}, headers=_auth_headers(token)
    )
    assert activate_second.status_code == 200

    active_count = await db_session.scalar(
        select(func.count()).select_from(ModelVersion).where(ModelVersion.is_active.is_(True))
    )
    assert active_count == 1
    refreshed_first = await db_session.get(ModelVersion, first_id)
    assert refreshed_first is not None
    assert refreshed_first.is_active is False
