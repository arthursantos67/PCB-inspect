"""`OpenAICompatibleClient.complete_chat` (issue #32's addition to the Issue #16/#31 LLM
client) — the tool-calling completion call the chat agent drives. Mirrors
tests/test_health.py's `_FakeAsyncClient` convention for stubbing `httpx.AsyncClient` without a
real network call.
"""

import json as json_lib
from typing import Any

import httpx
import pytest

from app.agents import llm_client as llm_client_module
from app.agents.llm_client import LLMUnavailableError, OpenAICompatibleClient


class _FakeResponse:
    """Every test here uses a 200 response — a non-2xx status is already covered by
    `complete_json`'s equivalent tests, and the error branch is shared code.
    """

    is_error = False
    status_code = 200
    text = ""

    def __init__(self, json_body: dict[str, Any]) -> None:
        self._json_body = json_body

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


async def test_complete_chat_keeps_provider_extra_content_on_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini 3.x signs each tool call with a `thought_signature` under `extra_content` and
    returns 400 INVALID_ARGUMENT if the follow-up request carrying the tool result does not
    hand it back. Dropping it here broke every chat question that needed a tool while bare
    greetings, which need none, kept working.
    """
    signature = {"google": {"thought_signature": "El4KXAER"}}
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
                                    "extra_content": signature,
                                    "function": {"name": "list_batches", "arguments": "{}"},
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

    assert result.tool_calls[0].extra_content == signature


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


# --- stream_chat -----------------------------------------------------------------------------
# The streaming path is what the chat agent actually drives in production (`_complete` prefers
# it); `complete_chat` above is only the fallback the scripted stubs use. It went untested until
# a provider signing its tool calls made the difference matter, so the reassembly it does that
# `complete_chat` does not — fragments split mid-JSON, keyed by index — is covered here.


class _FakeStreamResponse:
    def __init__(self, lines: list[str], status_code: int = 200, body: str = "") -> None:
        self._lines = lines
        self.status_code = status_code
        self.is_error = status_code >= 400
        self.text = body

    async def __aenter__(self) -> "_FakeStreamResponse":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def aread(self) -> bytes:
        return self.text.encode()

    async def aiter_lines(self) -> Any:
        for line in self._lines:
            yield line


class _FakeStreamingClient:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response
        self.requests: list[dict[str, Any]] = []

    async def __aenter__(self) -> "_FakeStreamingClient":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    def stream(
        self, method: str, url: str, json: dict[str, Any], headers: dict[str, str] | None = None
    ) -> _FakeStreamResponse:
        self.requests.append(json)
        return self._response


def _sse(payload: dict[str, Any]) -> str:
    # Aliased at import because `stream`/`post` below must keep `json` as a parameter name to
    # match how `httpx.AsyncClient` is called.
    return f"data: {json_lib.dumps(payload)}"


async def test_stream_chat_reassembles_tool_call_fragments_with_extra_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`function.arguments` arrives split across chunks and the provider's signature rides on
    only one of them, so both have to survive the merge (`_merge_tool_call_fragment`).
    """
    signature = {"google": {"thought_signature": "El4KXAER"}}
    fake_client = _FakeStreamingClient(
        _FakeStreamResponse(
            [
                _sse(
                    {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": "call-1",
                                            "extra_content": signature,
                                            "function": {
                                                "name": "list_batches",
                                                "arguments": '{"lim',
                                            },
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                ),
                _sse(
                    {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_calls": [
                                        {"index": 0, "function": {"arguments": 'it":20}'}}
                                    ]
                                },
                                "finish_reason": "tool_calls",
                            }
                        ]
                    }
                ),
                "data: [DONE]",
            ]
        )
    )
    monkeypatch.setattr(llm_client_module.httpx, "AsyncClient", lambda **kwargs: fake_client)
    client = OpenAICompatibleClient(
        base_url="http://localhost:1234/v1", model="local-model", api_key=None, timeout_s=10
    )

    chunks = [
        chunk
        async for chunk in client.stream_chat(
            messages=[{"role": "user", "content": "how many batches?"}], tools=[]
        )
    ]

    completion = chunks[-1].completion
    assert completion is not None
    assert len(completion.tool_calls) == 1
    call = completion.tool_calls[0]
    assert call.name == "list_batches"
    assert call.arguments == {"limit": 20}
    assert call.extra_content == signature
    assert fake_client.requests[0]["stream"] is True


async def test_stream_chat_error_reports_the_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare "400 Bad Request" is undiagnosable against a hosted provider: the body is the
    only place it says which part of the request it rejected.
    """
    fake_client = _FakeStreamingClient(
        _FakeStreamResponse(
            [],
            status_code=400,
            body='{"error": {"message": "Function call is missing a thought_signature"}}',
        )
    )
    monkeypatch.setattr(llm_client_module.httpx, "AsyncClient", lambda **kwargs: fake_client)
    client = OpenAICompatibleClient(
        base_url="http://localhost:1234/v1", model="local-model", api_key=None, timeout_s=10
    )

    with pytest.raises(LLMUnavailableError, match="thought_signature"):
        async for _chunk in client.stream_chat(
            messages=[{"role": "user", "content": "hi"}], tools=[]
        ):
            pass
