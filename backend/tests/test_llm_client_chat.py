"""`OpenAICompatibleClient.complete_chat` (issue #32's addition to the Issue #16/#31 LLM
client) — the tool-calling completion call the chat agent drives. Mirrors
tests/test_health.py's `_FakeAsyncClient` convention for stubbing `httpx.AsyncClient` without a
real network call.
"""

from typing import Any

import httpx
import pytest

from app.agents import llm_client as llm_client_module
from app.agents.llm_client import LLMUnavailableError, OpenAICompatibleClient


class _FakeResponse:
    """Every test here uses a 200 response — a non-2xx status is already covered by
    `complete_json`'s equivalent tests, and `raise_for_status` is shared code.
    """

    def __init__(self, json_body: dict[str, Any]) -> None:
        self._json_body = json_body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._json_body


class _FakeAsyncClient:
    def __init__(
        self, response: _FakeResponse | None = None, raise_exc: Exception | None = None
    ) -> None:
        self._response = response
        self._raise_exc = raise_exc
        self.requests: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def post(
        self, url: str, json: dict[str, Any], headers: dict[str, str] | None = None
    ) -> _FakeResponse:
        self.requests.append((url, json, headers or {}))
        if self._raise_exc is not None:
            raise self._raise_exc
        assert self._response is not None
        return self._response


def _patch_client(monkeypatch: pytest.MonkeyPatch, fake_client: _FakeAsyncClient) -> None:
    monkeypatch.setattr(llm_client_module.httpx, "AsyncClient", lambda **kwargs: fake_client)


async def test_complete_chat_sends_tools_and_parses_plain_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeAsyncClient(
        response=_FakeResponse(
            {
                "choices": [{"message": {"role": "assistant", "content": "hello"}}],
                "usage": {"total_tokens": 42},
            }
        )
    )
    _patch_client(monkeypatch, fake_client)
    client = OpenAICompatibleClient(
        base_url="http://localhost:1234/v1", model="local-model", api_key=None, timeout_s=10
    )

    result = await client.complete_chat(
        messages=[{"role": "user", "content": "hi"}], tools=[{"type": "function", "function": {}}]
    )

    assert result.content == "hello"
    assert result.tool_calls == []
    assert client.total_tokens_used == 42
    url, payload, _headers = fake_client.requests[0]
    assert url == "http://localhost:1234/v1/chat/completions"
    assert payload["tools"] == [{"type": "function", "function": {}}]
    assert payload["tool_choice"] == "auto"


async def test_complete_chat_parses_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeAsyncClient(
        response=_FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "function": {
                                        "name": "get_defect_knowledge",
                                        "arguments": '{"defect_type": "spur"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        )
    )
    _patch_client(monkeypatch, fake_client)
    client = OpenAICompatibleClient(
        base_url="http://localhost:1234/v1", model="local-model", api_key=None, timeout_s=10
    )

    result = await client.complete_chat(messages=[{"role": "user", "content": "hi"}], tools=[])

    assert result.content is None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "get_defect_knowledge"
    assert result.tool_calls[0].arguments == {"defect_type": "spur"}


async def test_complete_chat_omits_tools_and_tool_choice_when_no_tools_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeAsyncClient(
        response=_FakeResponse({"choices": [{"message": {"content": "hi"}}]})
    )
    _patch_client(monkeypatch, fake_client)
    client = OpenAICompatibleClient(
        base_url="http://localhost:1234/v1", model="local-model", api_key=None, timeout_s=10
    )

    await client.complete_chat(messages=[{"role": "user", "content": "hi"}], tools=[])

    _url, payload, _headers = fake_client.requests[0]
    assert "tools" not in payload
    assert "tool_choice" not in payload


async def test_complete_chat_wraps_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeAsyncClient(raise_exc=httpx.ConnectError("connection refused"))
    _patch_client(monkeypatch, fake_client)
    client = OpenAICompatibleClient(
        base_url="http://localhost:1234/v1", model="local-model", api_key=None, timeout_s=10
    )

    with pytest.raises(LLMUnavailableError):
        await client.complete_chat(messages=[{"role": "user", "content": "hi"}], tools=[])


async def test_complete_chat_wraps_malformed_tool_call_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeAsyncClient(
        response=_FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "function": {
                                        "name": "get_defect_knowledge",
                                        "arguments": "{bad json",
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        )
    )
    _patch_client(monkeypatch, fake_client)
    client = OpenAICompatibleClient(
        base_url="http://localhost:1234/v1", model="local-model", api_key=None, timeout_s=10
    )

    with pytest.raises(LLMUnavailableError):
        await client.complete_chat(messages=[{"role": "user", "content": "hi"}], tools=[])
