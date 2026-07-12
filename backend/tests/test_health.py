"""`/health` worker-check tests (issue #21, item 6): `check_worker` must report `error` when
any expected queue (inference/agents/housekeeping) has no worker consuming it, not just when
zero workers respond at all — a plain `control.ping()` can't tell the difference between "all
workers up" and "only worker-inference up, worker-agents dead".
"""

from typing import Any

import pytest

from app.core.config import get_settings
from app.core.health import check_worker


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
