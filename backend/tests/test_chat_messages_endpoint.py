"""`POST /api/v1/chat/sessions/{id}/messages` (FR-09, PRD section 11.2) — the full SSE
message-turn endpoint. The generator started by `StreamingResponse` here always terminates
(unlike `GET /api/v1/events`'s intentionally-infinite stream, see tests/test_events.py's module
docstring), so this can be exercised over real HTTP via `httpx.AsyncClient`/`ASGITransport`
without the deadlock that forces that other test file to call its generator directly.
"""

import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_client import ChatCompletion, ToolCallRequest
from app.chat import router as chat_router_module

ACCOUNT = {
    "email": "operator@pcb-inspect.local",
    "password": "correct-horse-battery",
    "full_name": "Operator",
}
OTHER_ACCOUNT_CREATE = {
    "email": "other@pcb-inspect.local",
    "password": "another-horse-battery",
    "full_name": "Other Operator",
}


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _setup_account(client: AsyncClient) -> str:
    response = await client.post("/api/v1/auth/setup", json=ACCOUNT)
    return response.json()["access_token"]


async def _create_second_account_token(client: AsyncClient, first_account_token: str) -> str:
    await client.post(
        "/api/v1/users", json=OTHER_ACCOUNT_CREATE, headers=_auth_headers(first_account_token)
    )
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": OTHER_ACCOUNT_CREATE["email"], "password": OTHER_ACCOUNT_CREATE["password"]},
    )
    return response.json()["access_token"]


def _parse_sse_events(raw: str) -> list[dict]:
    events = []
    for chunk in raw.split("\n\n"):
        if not chunk.strip():
            continue
        event_type = None
        data = None
        for line in chunk.split("\n"):
            if line.startswith("event:"):
                event_type = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:") :].strip())
        events.append({"event": event_type, "data": data})
    return events


class _StubChatLLMClient:
    def __init__(self, responses: list[ChatCompletion]) -> None:
        self._responses = list(responses)

    async def complete_chat(self, **kwargs: object) -> ChatCompletion:
        return self._responses.pop(0)


def _patch_llm_client(monkeypatch: pytest.MonkeyPatch, client: object | None) -> None:
    async def _fake_build_llm_client(db: AsyncSession) -> object | None:
        return client

    monkeypatch.setattr(chat_router_module, "build_llm_client", _fake_build_llm_client)


async def test_send_message_streams_tool_call_and_content_then_persists_history(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = await _setup_account(client)
    session_id = (
        await client.post("/api/v1/chat/sessions", json={}, headers=_auth_headers(token))
    ).json()["id"]

    tool_call = ToolCallRequest(
        id="c1", name="get_defect_knowledge", arguments={"defect_type": "spur"}
    )
    _patch_llm_client(
        monkeypatch,
        _StubChatLLMClient(
            [
                ChatCompletion(content=None, tool_calls=[tool_call]),
                ChatCompletion(content="A spur is a stray copper sliver.", tool_calls=[]),
            ]
        ),
    )

    response = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "What is a spur defect?"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert events[0] == {
        "event": "tool_call",
        "data": {"name": "get_defect_knowledge", "arguments": {"defect_type": "spur"}},
    }
    content = "".join(e["data"]["text"] for e in events if e["event"] == "content_delta")
    assert content == "A spur is a stray copper sliver."
    done_event = events[-1]
    assert done_event["event"] == "done"
    assert done_event["data"]["content"] == "A spur is a stray copper sliver."
    assert done_event["data"]["role"] == "assistant"
    assert done_event["data"]["tool_calls"][0]["name"] == "get_defect_knowledge"

    history = await client.get(
        f"/api/v1/chat/sessions/{session_id}", headers=_auth_headers(token)
    )
    messages = history.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "What is a spur defect?"
    assert messages[1]["content"] == "A spur is a stray copper sliver."
    assert messages[1]["tool_calls"][0]["name"] == "get_defect_knowledge"
    # The session's title is derived from the first message (PRD 10.2).
    assert history.json()["title"] == "What is a spur defect?"


async def test_send_message_with_no_llm_configured_degrades_gracefully(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = await _setup_account(client)
    session_id = (
        await client.post("/api/v1/chat/sessions", json={}, headers=_auth_headers(token))
    ).json()["id"]
    _patch_llm_client(monkeypatch, None)

    response = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "hi"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert events[0]["event"] == "error"

    # UC-7's alternative flow: the session (and the operator's question) survive the failure.
    history = await client.get(
        f"/api/v1/chat/sessions/{session_id}", headers=_auth_headers(token)
    )
    messages = history.json()["messages"]
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "hi"
    assert messages[1]["role"] == "assistant"


async def test_send_message_to_a_session_owned_by_another_account_is_forbidden(
    client: AsyncClient,
) -> None:
    token = await _setup_account(client)
    other_token = await _create_second_account_token(client, token)
    session_id = (
        await client.post("/api/v1/chat/sessions", json={}, headers=_auth_headers(token))
    ).json()["id"]

    response = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "hi"},
        headers=_auth_headers(other_token),
    )

    assert response.status_code == 403


async def test_send_message_requires_authentication(client: AsyncClient) -> None:
    token = await _setup_account(client)
    session_id = (
        await client.post("/api/v1/chat/sessions", json={}, headers=_auth_headers(token))
    ).json()["id"]

    response = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "hi"}
    )

    assert response.status_code == 401
