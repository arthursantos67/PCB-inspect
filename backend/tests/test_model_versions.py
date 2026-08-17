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

from app.core.config import get_settings
from app.models import AuditLog, ModelVersion
from app.models.enums import ModelEvaluationStatus
from app.settings import models_router, models_service

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


# --- Upload (FR-12) -----------------------------------------------------------------------

# What a checkpoint saved by a current `torch.save` starts with: it is a ZIP archive.
_TORCH_CHECKPOINT_BYTES = b"PK\x03\x04" + b"\x00" * 64


@pytest.fixture
def weights_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Points uploads at the test's own directory instead of the real app-data volume."""
    settings = get_settings().model_copy(update={"app_data_dir": tmp_path / "app-data"})
    monkeypatch.setattr(models_service, "get_settings", lambda: settings)
    return settings.uploaded_weights_dir


async def _upload(
    client: AsyncClient,
    token: str,
    *,
    version: str,
    content: bytes,
    filename: str = "best.pt",
) -> object:
    return await client.post(
        "/api/v1/settings/models/upload",
        data={"version": version},
        files={"file": (filename, content, "application/octet-stream")},
        headers=_auth_headers(token),
    )


async def test_upload_stores_the_weights_and_registers_a_pending_version(
    client: AsyncClient,
    weights_dir: Path,
    db_session: AsyncSession,
    _stub_tasks: dict[str, _FakeTask],
) -> None:
    """The uploaded file is copied into managed storage (the operator's download folder isn't
    durable) and then goes through the exact same gate as a path registration: PENDING, no
    metrics, evaluation enqueued, nothing activated.
    """
    token = await _setup_account(client)

    response = await _upload(client, token, version="up-1", content=_TORCH_CHECKPOINT_BYTES)

    assert response.status_code == 201
    body = response.json()
    assert body["evaluation_status"] == "PENDING"
    assert body["metrics"] is None
    assert body["is_active"] is False
    assert body["weights_path"] == str(weights_dir / "up-1.pt")
    assert (weights_dir / "up-1.pt").read_bytes() == _TORCH_CHECKPOINT_BYTES
    assert _stub_tasks["evaluation"].calls == [(body["id"],)]

    audit = await db_session.scalar(
        select(AuditLog).where(AuditLog.action == "model.registered")
    )
    assert audit is not None
    assert audit.payload["source"] == "upload"


async def test_upload_rejects_a_file_that_is_not_a_torch_checkpoint(
    client: AsyncClient, weights_dir: Path, db_session: AsyncSession
) -> None:
    """Read from the file's own header, not its extension — same rule ingestion applies to
    images. A rejected upload must leave neither a row nor a half-written file behind.
    """
    token = await _setup_account(client)

    response = await _upload(
        client, token, version="up-2", content=b"this is a jpeg someone renamed"
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert (await db_session.scalar(select(func.count()).select_from(ModelVersion))) == 0
    assert list(weights_dir.glob("*")) == []


async def test_upload_rejects_an_empty_file(
    client: AsyncClient, weights_dir: Path, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)

    response = await _upload(client, token, version="up-3", content=b"")

    assert response.status_code == 422
    assert (await db_session.scalar(select(func.count()).select_from(ModelVersion))) == 0
    assert list(weights_dir.glob("*")) == []


async def test_upload_rejects_a_version_name_already_registered(
    client: AsyncClient, tmp_path: Path, weights_dir: Path
) -> None:
    """Checked before a single byte is written, so a duplicate upload can never overwrite the
    weights an existing version points at.
    """
    token = await _setup_account(client)
    await client.post(
        "/api/v1/settings/models",
        json={"version": "up-4", "weights_path": str(_weights_file(tmp_path))},
        headers=_auth_headers(token),
    )

    response = await _upload(client, token, version="up-4", content=_TORCH_CHECKPOINT_BYTES)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODEL_VERSION_EXISTS"
    assert list(weights_dir.glob("*")) == []


async def test_upload_rejects_a_version_name_that_is_not_a_safe_file_name(
    client: AsyncClient, weights_dir: Path, db_session: AsyncSession
) -> None:
    """The version string becomes the stored file's name, so it must not be able to walk out
    of the weights directory.
    """
    token = await _setup_account(client)

    response = await _upload(
        client, token, version="../../etc/passwd", content=_TORCH_CHECKPOINT_BYTES
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert (await db_session.scalar(select(func.count()).select_from(ModelVersion))) == 0
    assert list(weights_dir.glob("*")) == []


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
