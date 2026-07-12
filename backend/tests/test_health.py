"""`/health` worker-check tests (issue #21, item 6): `check_worker` must report `error` when
any expected queue (inference/agents/housekeeping) has no worker consuming it, not just when
zero workers respond at all — a plain `control.ping()` can't tell the difference between "all
workers up" and "only worker-inference up, worker-agents dead".
"""

from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.health as health_module
from app.core.config import get_settings
from app.core.health import check_llm, check_worker
from app.models import SystemConfig


class _FakeInspect:
    def __init__(self, active_queues: dict[str, list[dict[str, Any]]] | None) -> None:
        self._active_queues = active_queues

    def active_queues(self) -> dict[str, list[dict[str, Any]]] | None:
        return self._active_queues


def _queue(name: str) -> dict[str, Any]:
    return {"name": name, "exchange": {}, "routing_key": name}


def _patch_inspect(
    monkeypatch: pytest.MonkeyPatch, active_queues: dict[str, list[dict[str, Any]]] | None
) -> None:
    from app.tasks.celery_app import celery_app

    monkeypatch.setattr(
        celery_app.control, "inspect", lambda timeout=1.0: _FakeInspect(active_queues)
    )


async def test_all_expected_queues_covered_reports_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_inspect(
        monkeypatch,
        {
            "celery@inference-1": [_queue("inference")],
            "celery@agents-1": [_queue("agents")],
            "celery@housekeeping-1": [_queue("housekeeping")],
        },
    )

    result = await check_worker(get_settings())

    assert result.status == "ok"


async def test_missing_agents_worker_reports_error_not_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact scenario from issue #21 item 6: worker-agents is dead, only worker-inference
    (and worker-housekeeping) respond — must not read as "ok" just because someone replied.
    """
    _patch_inspect(
        monkeypatch,
        {
            "celery@inference-1": [_queue("inference")],
            "celery@housekeeping-1": [_queue("housekeeping")],
        },
    )

    result = await check_worker(get_settings())

    assert result.status == "error"
    assert result.detail is not None
    assert "agents" in result.detail


async def test_no_worker_responding_reports_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_inspect(monkeypatch, None)

    result = await check_worker(get_settings())

    assert result.status == "error"
    assert result.detail == "no worker responded"


async def test_ping_exception_reports_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks.celery_app import celery_app

    def _raise(timeout: float = 1.0) -> Any:
        raise ConnectionError("broker unreachable")

    monkeypatch.setattr(celery_app.control, "inspect", _raise)

    result = await check_worker(get_settings())

    assert result.status == "error"
    assert "broker unreachable" in (result.detail or "")


# --- check_llm (issue #30, item 2): real reachability, not the previous static "unverified") ---


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeAsyncClient:
    """Stands in for `httpx.AsyncClient` so tests never make a real network call — records
    every `get()` (url, headers) so a test can assert the probe hit the right endpoint/auth.
    """

    def __init__(
        self, response: _FakeResponse | None = None, raise_exc: Exception | None = None
    ) -> None:
        self._response = response
        self._raise_exc = raise_exc
        self.requests: list[tuple[str, dict[str, str]]] = []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def get(self, url: str, headers: dict[str, str] | None = None) -> _FakeResponse:
        self.requests.append((url, headers or {}))
        if self._raise_exc is not None:
            raise self._raise_exc
        assert self._response is not None
        return self._response


def _patch_llm_client(monkeypatch: pytest.MonkeyPatch, fake_client: _FakeAsyncClient) -> None:
    monkeypatch.setattr(health_module.httpx, "AsyncClient", lambda **kwargs: fake_client)


async def test_check_llm_local_default_reachable_reports_ok(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """No `SystemConfig` overrides at all — must fall back to the env defaults (local
    `openai_compatible` endpoint, section 5.2) rather than reporting `not_configured`.
    """
    fake_client = _FakeAsyncClient(response=_FakeResponse(200))
    _patch_llm_client(monkeypatch, fake_client)

    result = await check_llm(get_settings(), db_session)

    assert result.status == "ok"
    assert "openai_compatible" in (result.detail or "")
    url, _headers = fake_client.requests[0]
    assert url.endswith("/models")


async def test_check_llm_unreachable_endpoint_reports_error(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    fake_client = _FakeAsyncClient(raise_exc=httpx.ConnectError("connection refused"))
    _patch_llm_client(monkeypatch, fake_client)

    result = await check_llm(get_settings(), db_session)

    assert result.status == "error"
    assert "unreachable" in (result.detail or "")


async def test_check_llm_http_error_status_reports_error(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    fake_client = _FakeAsyncClient(response=_FakeResponse(401))
    _patch_llm_client(monkeypatch, fake_client)

    result = await check_llm(get_settings(), db_session)

    assert result.status == "error"
    assert "http_status=401" in (result.detail or "")


async def test_check_llm_cloud_provider_without_api_key_reports_not_configured(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """A cloud provider (never the default, section 5.2) reports `not_configured` — not an
    error — until the operator explicitly opts in with an API key.
    """
    db_session.add(SystemConfig(key="llm.provider", value="anthropic", is_secret=False))
    await db_session.flush()
    fake_client = _FakeAsyncClient(response=_FakeResponse(200))
    _patch_llm_client(monkeypatch, fake_client)

    result = await check_llm(get_settings(), db_session)

    assert result.status == "not_configured"
    assert fake_client.requests == []  # never even attempted the probe


async def test_check_llm_cloud_provider_with_api_key_probes_with_auth_header(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    db_session.add(SystemConfig(key="llm.provider", value="anthropic", is_secret=False))
    db_session.add(
        SystemConfig(
            key="llm.api_key",
            value={"ciphertext": None, "last4": None},
            is_secret=True,
        )
    )
    await db_session.flush()

    # Bypass encryption plumbing here — this test is about the reachability probe, not
    # encrypt/decrypt round-tripping (already covered by test_settings.py).
    async def _fake_get_secret(db: AsyncSession, key: str) -> str | None:
        return "sk-ant-fake-key" if key == "llm.api_key" else None

    monkeypatch.setattr("app.settings.service.get_secret_config_value", _fake_get_secret)

    fake_client = _FakeAsyncClient(response=_FakeResponse(200))
    _patch_llm_client(monkeypatch, fake_client)

    result = await check_llm(get_settings(), db_session)

    assert result.status == "ok"
    url, headers = fake_client.requests[0]
    assert url == "https://api.anthropic.com/v1/models"
    assert headers["x-api-key"] == "sk-ant-fake-key"
