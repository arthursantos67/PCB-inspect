"""LLM client abstraction for the agent chain (FR-06's agents tier, section 5.2, issue #31).

Local-first by default: `openai_compatible` targets an OpenAI-compatible `/chat/completions`
endpoint (LM Studio/Ollama/vLLM running on the same machine, section 3.1) using structured
JSON output. `anthropic`/`google` are configurable opt-ins at the `SystemConfig` layer
(issue #30) but have no client implementation here yet — `build_llm_client` reports them as
"not configured" for this chain rather than guessing at an unimplemented integration; wiring a
real cloud client is deferred to whichever issue actually exposes that opt-in end-to-end.

One client shape, but not necessarily one endpoint: `build_llm_client` takes an `LLMRole`
(`chat`/`analysis`/`report`) and resolves that tier's `base_url`/`model`/`api_key`, falling
back field by field to the shared `llm.*` values. That is what lets the chat run on a fast,
cheap hosted model while the report tier runs on a larger one and the analysis chain on a
third, without any of them needing a separate client implementation — every provider in play
speaks the same OpenAI-compatible dialect.

Every failure mode (unreachable endpoint, non-2xx response, malformed JSON) is normalized to
`LLMUnavailableError` so callers have exactly one exception type to handle — see
`app.agents.chain`, which treats it as "degrade to the baseline," never a task crash (the
"No LLM Configured => No Crash" acceptance criterion).
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.settings.service import get_config_value, get_secret_config_value

logger = logging.getLogger(__name__)

#: Extra attempts a structured call gets when the endpoint answers 429. Two is enough to ride
#: out the per-minute token bucket a hosted provider refills continuously, and small enough
#: that a genuinely exhausted quota still degrades to the baseline promptly.
_RATE_LIMIT_RETRIES = 2

#: Longest `Retry-After` worth honouring. Beyond this the provider is not throttling a burst,
#: it is out of quota, and holding a Celery worker for a minute to find that out is worse than
#: degrading now.
_MAX_RETRY_AFTER_S = 20.0

#: Used when a 429 carries no usable `Retry-After`, which is common enough to need an answer.
_DEFAULT_RETRY_AFTER_S = 5.0


def _retry_after_seconds(header: str | None) -> float | None:
    """Seconds to wait before retrying a 429, or `None` if it is not worth waiting.

    Only the delta-seconds form of `Retry-After` is read; the HTTP-date form is rare on JSON
    APIs and a misparse here would either hang the worker or hammer the endpoint, so an
    unparseable value falls back to the fixed default rather than being guessed at.
    """
    try:
        delay = float(header) if header else _DEFAULT_RETRY_AFTER_S
    except ValueError:
        delay = _DEFAULT_RETRY_AFTER_S
    return delay if delay <= _MAX_RETRY_AFTER_S else None


class LLMUnavailableError(Exception):
    """The configured LLM could not be reached or returned an unusable response."""


class LLMClient(Protocol):
    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        """Runs a single structured-output completion call and returns the parsed JSON
        object. Raises `LLMUnavailableError` on any failure — never returns a partial/None
        result.
        """
        ...


@dataclass(frozen=True)
class ToolCallRequest:
    """One function call the model asked for (issue #32's chat agent, section 5.4).

    `extra_content` is whatever provider-specific bookkeeping rode along with the call, kept
    opaque and echoed back verbatim on the follow-up request that carries the tool result.
    Gemini 3.x is why this exists: it attaches an `extra_content.google.thought_signature` to
    every tool call and rejects the next request with a 400 INVALID_ARGUMENT if the signature
    is not returned with the call it belongs to. Dropping it made every question that needed a
    tool fail while bare greetings, which need none, kept working.
    """

    id: str
    name: str
    arguments: dict[str, Any]
    extra_content: dict[str, Any] | None = None


@dataclass(frozen=True)
class ChatCompletion:
    """One assistant turn from `ChatLLMClient.complete_chat`: either free-text `content`, or
    one or more `tool_calls` to run before the model can produce a final answer — never both
    populated at once in the OpenAI tool-calling contract this mirrors.
    """

    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)


@dataclass(frozen=True)
class ChatStreamChunk:
    """One piece of a streamed assistant turn (`ChatLLMClient.stream_chat`): either a slice of
    freshly generated text (`text`), or the terminal `completion` carrying the fully assembled
    turn. Exactly one of the two is populated.
    """

    text: str | None = None
    completion: ChatCompletion | None = None


class ChatLLMClient(Protocol):
    async def complete_chat(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ChatCompletion:
        """Runs one multi-turn, tool-calling-capable completion call. Raises
        `LLMUnavailableError` on any failure, exactly like `complete_json`.
        """
        ...


class AgentLLMClient(LLMClient, ChatLLMClient, Protocol):
    """Both capabilities together — what `build_llm_client` actually returns. The analysis
    chain (`app.agents.chain`) only ever calls `complete_json` and the chat agent
    (`app.chat.agent`) only ever calls `complete_chat`, so each keeps annotating its parameter
    with just the narrower protocol it needs; this is only the shared factory's return type.
    """


class OpenAICompatibleClient:
    """Targets `{base_url}/chat/completions` with `response_format: json_object` — the
    OpenAI-compatible shape LM Studio/Ollama/vLLM (and OpenAI itself) all implement.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        timeout_s: float,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout_s = timeout_s
        self._max_tokens = max_tokens
        self._reasoning_effort = reasoning_effort
        self.total_tokens_used: int | None = None

    @property
    def provider(self) -> str:
        return "openai_compatible"

    @property
    def model(self) -> str:
        return self._model

    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        if self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort
        try:
            body = await self._post_completion(payload)
            content = body["choices"][0]["message"]["content"]
            self._record_usage(body)
            return dict(json.loads(content))
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailableError(f"LLM response missing expected shape: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise LLMUnavailableError(f"LLM response content was not valid JSON: {exc}") from exc

    async def _post_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POSTs one non-streaming completion, retrying while the endpoint says we are going
        too fast, and normalizing everything else to `LLMUnavailableError`.

        The retry exists for the analysis chain specifically: it fires three-plus structured
        calls back to back for a single board, which is exactly the shape a per-minute token
        budget rejects, and without it one 429 in the middle discards the whole chain's work
        and falls back to the baseline. `Retry-After` is honoured but capped — a provider
        asking us to wait longer than `_MAX_RETRY_AFTER_S` is telling us the budget is
        exhausted, not that another second would help.

        Failures carry the response body, not just the status line. A bare
        `400 Bad Request` from a hosted provider is undiagnosable; the body is where the
        provider says *which* part of the request it disliked.
        """
        attempts = _RATE_LIMIT_RETRIES + 1
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as http_client:
                for attempt in range(attempts):
                    response = await http_client.post(
                        f"{self._base_url}/chat/completions",
                        json=payload,
                        headers=self._headers(),
                    )
                    if response.status_code == httpx.codes.TOO_MANY_REQUESTS and (
                        attempt < attempts - 1
                    ):
                        delay = _retry_after_seconds(response.headers.get("retry-after"))
                        if delay is not None:  # None => waiting longer than the cap; give up.
                            logger.warning(
                                "LLM endpoint rate-limited %s; retrying in %.1fs (attempt %d/%d)",
                                self._model,
                                delay,
                                attempt + 1,
                                attempts,
                            )
                            await asyncio.sleep(delay)
                            continue
                    if response.is_error:
                        raise LLMUnavailableError(
                            f"LLM endpoint returned {response.status_code}: {response.text[:500]}"
                        )
                    return dict(response.json())
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(f"LLM endpoint unreachable: {exc}") from exc
        raise LLMUnavailableError(  # pragma: no cover - the loop always returns or raises
            f"LLM endpoint kept rate-limiting {self._model}"
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _chat_payload(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.2,
        }
        if self._max_tokens:
            payload["max_tokens"] = self._max_tokens
        if self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    def _record_usage(self, body: dict[str, Any]) -> None:
        usage_tokens = (body.get("usage") or {}).get("total_tokens")
        if isinstance(usage_tokens, int):
            self.total_tokens_used = (self.total_tokens_used or 0) + usage_tokens

    async def stream_chat(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[ChatStreamChunk]:
        """Token-level streaming variant of `complete_chat` (`stream: true`).

        This is what the chat agent uses in production: with a local model on CPU, a full
        answer takes tens of seconds to generate, and waiting for all of it before sending
        anything made the chat look frozen. Streaming does not make generation faster, it
        makes the *first* token reach the operator in
        about the time the model takes to process the prompt, with the rest arriving as it is
        written.

        Tool calls arrive fragmented across chunks in this format (`function.arguments` is
        split mid-JSON), so deltas are accumulated per `index` and only parsed once the stream
        ends — the reassembly the non-streaming path was originally written to avoid.
        """
        accumulated_content: list[str] = []
        tool_fragments: dict[int, dict[str, Any]] = {}
        finished = False
        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout_s) as http_client,
                http_client.stream(
                    "POST",
                    f"{self._base_url}/chat/completions",
                    json={**self._chat_payload(messages=messages, tools=tools), "stream": True},
                    headers=self._headers(),
                ) as response,
            ):
                if response.is_error:
                    # `raise_for_status` would report the status line only, and a bare
                    # `400 Bad Request` from a hosted provider is undiagnosable — the body is
                    # where it says which part of the request it rejected.
                    await response.aread()
                    raise LLMUnavailableError(
                        f"LLM endpoint returned {response.status_code}: {response.text[:500]}"
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        finished = True
                        break
                    body = json.loads(data)
                    self._record_usage(body)
                    choices = body.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    text = delta.get("content")
                    if text:
                        accumulated_content.append(text)
                        yield ChatStreamChunk(text=text)
                    for fragment in delta.get("tool_calls") or []:
                        self._merge_tool_call_fragment(tool_fragments, fragment)
                    if choices[0].get("finish_reason"):
                        finished = True
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(f"LLM endpoint unreachable: {exc}") from exc
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailableError(f"LLM stream had an unexpected shape: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise LLMUnavailableError(f"LLM stream sent invalid JSON: {exc}") from exc

        if not finished and not accumulated_content and not tool_fragments:
            raise LLMUnavailableError("LLM stream closed before sending anything")

        yield ChatStreamChunk(
            completion=ChatCompletion(
                content="".join(accumulated_content) or None,
                tool_calls=self._assemble_tool_calls(tool_fragments),
            )
        )

    @staticmethod
    def _merge_tool_call_fragment(
        fragments: dict[int, dict[str, Any]], fragment: dict[str, Any]
    ) -> None:
        index = fragment.get("index") or 0
        current = fragments.setdefault(
            index, {"id": None, "name": None, "arguments": "", "extra_content": None}
        )
        if fragment.get("id"):
            current["id"] = fragment["id"]
        if fragment.get("extra_content"):
            # Provider bookkeeping (see `ToolCallRequest.extra_content`). Only ever arrives on
            # one fragment of the call, so last-writer-wins is enough.
            current["extra_content"] = fragment["extra_content"]
        function = fragment.get("function") or {}
        if function.get("name"):
            current["name"] = function["name"]
        if function.get("arguments"):
            current["arguments"] += function["arguments"]

    @staticmethod
    def _assemble_tool_calls(fragments: dict[int, dict[str, Any]]) -> list[ToolCallRequest]:
        calls = []
        for index in sorted(fragments):
            fragment = fragments[index]
            if not fragment["name"]:
                continue
            try:
                arguments = json.loads(fragment["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                raise LLMUnavailableError(
                    f"LLM tool call arguments were not valid JSON: {exc}"
                ) from exc
            calls.append(
                ToolCallRequest(
                    id=fragment["id"] or f"call-{index}",
                    name=fragment["name"],
                    arguments=arguments if isinstance(arguments, dict) else {},
                    extra_content=fragment.get("extra_content"),
                )
            )
        return calls

    async def complete_chat(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ChatCompletion:
        """Same endpoint as `complete_json`, but with the OpenAI tool-calling contract instead
        of forced `json_object` output — the chat agent's turns are free text or tool calls,
        never a single structured JSON blob (`app.chat.agent`).
        """
        headers = self._headers()
        payload = self._chat_payload(messages=messages, tools=tools)
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as http_client:
                response = await http_client.post(
                    f"{self._base_url}/chat/completions", json=payload, headers=headers
                )
            if response.is_error:  # The body, not just the status line — see `stream_chat`.
                raise LLMUnavailableError(
                    f"LLM endpoint returned {response.status_code}: {response.text[:500]}"
                )
            body = response.json()
            message = body["choices"][0]["message"]
            self._record_usage(body)

            raw_tool_calls = message.get("tool_calls") or []
            tool_calls = [
                ToolCallRequest(
                    id=call["id"],
                    name=call["function"]["name"],
                    arguments=json.loads(call["function"]["arguments"] or "{}"),
                    extra_content=call.get("extra_content"),
                )
                for call in raw_tool_calls
            ]
            return ChatCompletion(content=message.get("content"), tool_calls=tool_calls)
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(f"LLM endpoint unreachable: {exc}") from exc
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailableError(f"LLM response missing expected shape: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise LLMUnavailableError(
                f"LLM tool call arguments were not valid JSON: {exc}"
            ) from exc


LLMRole = Literal["chat", "analysis", "report"]

#: Every role a caller may ask `build_llm_client` for. Kept as data (not just a type) so the
#: health check can iterate the same set the factory honours, instead of repeating the list.
LLM_ROLES: tuple[LLMRole, ...] = ("chat", "analysis", "report")


@dataclass(frozen=True)
class LLMConnection:
    """The three fields that identify *where* a role's completions go. Resolved by
    `resolve_llm_connection` so the client factory and the health probe agree by construction
    on what a given role is actually pointed at.
    """

    base_url: str | None
    model: str | None
    api_key: str | None
    reasoning_effort: str | None = None


async def resolve_llm_connection(
    db: AsyncSession, settings: Settings, role: LLMRole | None
) -> LLMConnection:
    """Resolves one role's endpoint, field by field, most specific source first:

        role in dynamic config -> role in env -> global in dynamic config -> global in env

    The fallback is per *field*, not per role, which is the whole point: a station that only
    wants a different chat model sets `llm.chat.model` and inherits the shared `llm.base_url`
    and `llm.api_key`, while a station whose roles live on different providers (Groq for the
    analysis/report tiers, Google for the chat tier) overrides all three. `role=None` skips
    the role layer entirely and resolves the plain globals.
    """

    async def field(suffix: str, global_default: Any) -> Any:
        if role is not None:
            scoped = await get_config_value(db, f"llm.{role}.{suffix}", None)
            if scoped:
                return scoped
            from_env = getattr(settings, f"llm_{role}_{suffix}", None)
            if from_env:
                return from_env
        return await get_config_value(db, f"llm.{suffix}", global_default)

    async def secret_field() -> str | None:
        if role is not None:
            scoped = await get_secret_config_value(db, f"llm.{role}.api_key")
            if scoped:
                return scoped
            from_env = getattr(settings, f"llm_{role}_api_key", None)
            if from_env:
                return str(from_env)
        return await get_secret_config_value(db, "llm.api_key") or settings.llm_api_key

    base_url = await field("base_url", settings.llm_base_url)
    model = await field("model", settings.llm_model)
    reasoning_effort = await field("reasoning_effort", settings.llm_reasoning_effort)
    return LLMConnection(
        base_url=str(base_url) if base_url else None,
        model=str(model) if model else None,
        api_key=await secret_field(),
        reasoning_effort=str(reasoning_effort) if reasoning_effort else None,
    )


async def build_llm_client(
    db: AsyncSession, settings: Settings | None = None, role: LLMRole | None = None
) -> AgentLLMClient | None:
    """Reads connection details from dynamic config (issue #30's `llm.*` keys, falling back
    to env defaults), and builds a client for it.

    `role` selects which tier's endpoint to use (`resolve_llm_connection`); omitting it
    resolves the shared globals, which is what every caller predating the split did.

    Returns `None` when there's nothing to call: the provider is a cloud provider with no
    client implemented yet, or a required field is blank. `None` is a normal, expected value
    here — callers must treat it as "skip the agent tier, keep the baseline," never as an
    error (Phase 1's default demo state ships with no real LLM behind the configured local
    endpoint, and that must never crash a task either — see `app.agents.chain`).
    """
    settings = settings or get_settings()
    provider = await get_config_value(db, "llm.provider", settings.llm_provider)
    if provider != "openai_compatible":
        logger.info("Agent chain: provider %r has no client implementation yet; skipping", provider)
        return None

    connection = await resolve_llm_connection(db, settings, role)
    if not connection.base_url or not connection.model:
        return None

    timeout_s = await get_config_value(db, "llm.timeout_s", settings.llm_timeout_s)
    max_tokens = await get_config_value(db, "llm.max_tokens", settings.llm_max_tokens)
    return OpenAICompatibleClient(
        base_url=connection.base_url,
        model=connection.model,
        api_key=connection.api_key,
        timeout_s=float(timeout_s),
        max_tokens=int(max_tokens) if max_tokens else None,
        reasoning_effort=connection.reasoning_effort,
    )
