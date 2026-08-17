"""`OpenAICompatibleClient.complete_json` at the HTTP layer — the structured call the whole
agent chain is built on. Covers the two things that only show up against a hosted provider:
the optional `reasoning_effort` passthrough, and what happens when the endpoint answers 429.

Stubs `httpx.AsyncClient` in the same style as tests/test_llm_client_chat.py rather than
standing up a server; `asyncio.sleep` is stubbed too, so a retry test costs no wall time.
"""

from typing import Any

import httpx
import pytest

from app.agents import llm_client as llm_client_module
from app.agents.llm_client import LLMUnavailableError, OpenAICompatibleClient

VALID_BODY: dict[str, Any] = {
    "choices": [{"message": {"content": '{"ok": true}'}}],
    "usage": {"total_tokens": 11},
}


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict[str, Any] | None = None, **kwargs: str):
        self.status_code = status_code
        self.text = kwargs.pop("text", "")
        self.headers = dict(kwargs)
        self._json_body = json_body or {}

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400

    def json(self) -> dict[str, Any]:
        return self._json_body


class _FakeAsyncClient:
    """Answers each POST with the next queued response, so a test can script a 429 followed
    by a 200 the way a token bucket actually behaves.
    """

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.payloads: list[dict[str, Any]] = []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def post(
        self, url: str, json: dict[str, Any], headers: dict[str, str] | None = None
    ) -> _FakeResponse:
        self.payloads.append(json)
        return self._responses.pop(0)


def _patch(
    monkeypatch: pytest.MonkeyPatch, responses: list[_FakeResponse]
) -> tuple[_FakeAsyncClient, list[float]]:
    fake = _FakeAsyncClient(responses)
    slept: list[float] = []

    async def _no_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(llm_client_module.httpx, "AsyncClient", lambda **kwargs: fake)
    monkeypatch.setattr(llm_client_module.asyncio, "sleep", _no_sleep)
    return fake, slept


def _client(**overrides: Any) -> OpenAICompatibleClient:
    kwargs: dict[str, Any] = {
        "base_url": "http://llm.local/v1",
        "model": "test-model",
        "api_key": None,
        "timeout_s": 5.0,
    }
    kwargs.update(overrides)
    return OpenAICompatibleClient(**kwargs)


async def test_reasoning_effort_is_sent_only_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake, _ = _patch(monkeypatch, [_FakeResponse(200, VALID_BODY), _FakeResponse(200, VALID_BODY)])

    await _client().complete_json(system="s", user="u")
    await _client(reasoning_effort="none").complete_json(system="s", user="u")

    # Omitted, not sent empty: a local LM Studio/Ollama endpoint has never heard of the field,
    # and some strict servers reject an unknown key outright.
    assert "reasoning_effort" not in fake.payloads[0]
    assert fake.payloads[1]["reasoning_effort"] == "none"


async def test_rate_limited_call_is_retried_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake, slept = _patch(
        monkeypatch,
        [_FakeResponse(429, **{"retry-after": "3"}), _FakeResponse(200, VALID_BODY)],
    )

    result = await _client().complete_json(system="s", user="u")

    assert result == {"ok": True}
    assert slept == [3.0]
    assert len(fake.payloads) == 2


async def test_rate_limit_without_retry_after_uses_the_default_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, slept = _patch(monkeypatch, [_FakeResponse(429), _FakeResponse(200, VALID_BODY)])

    await _client().complete_json(system="s", user="u")

    assert slept == [llm_client_module._DEFAULT_RETRY_AFTER_S]


async def test_a_retry_after_beyond_the_cap_fails_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Being told to come back in an hour means the quota is gone, not that the burst was too
    fast: waiting it out would pin a Celery worker for the whole window, so the chain degrades
    to the baseline now instead.
    """
    throttled = _FakeResponse(429, text="quota exceeded", **{"retry-after": "3600"})
    fake, slept = _patch(monkeypatch, [throttled])

    with pytest.raises(LLMUnavailableError, match="429"):
        await _client().complete_json(system="s", user="u")

    assert slept == []
    assert len(fake.payloads) == 1


async def test_persistent_rate_limiting_gives_up_after_the_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake, slept = _patch(monkeypatch, [_FakeResponse(429, text="slow down") for _ in range(3)])

    with pytest.raises(LLMUnavailableError):
        await _client().complete_json(system="s", user="u")

    assert len(fake.payloads) == llm_client_module._RATE_LIMIT_RETRIES + 1
    assert len(slept) == llm_client_module._RATE_LIMIT_RETRIES


async def test_error_message_carries_the_response_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hosted provider explains itself in the body and says nothing useful in the status
    line — `400 Bad Request` alone cannot be acted on.
    """
    _patch(monkeypatch, [_FakeResponse(400, text='{"error":{"code":"json_validate_failed"}}')])

    with pytest.raises(LLMUnavailableError, match="json_validate_failed"):
        await _client().complete_json(system="s", user="u")


async def test_transport_failure_is_still_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Exploding(_FakeAsyncClient):
        async def post(self, url: str, json: dict[str, Any], headers: Any = None) -> _FakeResponse:
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(llm_client_module.httpx, "AsyncClient", lambda **kwargs: _Exploding([]))

    with pytest.raises(LLMUnavailableError, match="unreachable"):
        await _client().complete_json(system="s", user="u")
