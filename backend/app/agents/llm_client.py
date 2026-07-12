"""LLM client abstraction for the agent chain (FR-06's agents tier, section 5.2, issue #31).

Local-first by default: `openai_compatible` targets an OpenAI-compatible `/chat/completions`
endpoint (LM Studio/Ollama/vLLM running on the same machine, section 3.1) using structured
JSON output. `anthropic`/`google` are configurable opt-ins at the `SystemConfig` layer
(issue #30) but have no client implementation here yet — `build_llm_client` reports them as
"not configured" for this chain rather than guessing at an unimplemented integration; wiring a
real cloud client is deferred to whichever issue actually exposes that opt-in end-to-end.

Every failure mode (unreachable endpoint, non-2xx response, malformed JSON) is normalized to
`LLMUnavailableError` so callers have exactly one exception type to handle — see
`app.agents.chain`, which treats it as "degrade to the baseline," never a task crash (the
"No LLM Configured => No Crash" acceptance criterion).
"""

import json
import logging
from typing import Any, Protocol

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.settings.service import get_config_value, get_secret_config_value

logger = logging.getLogger(__name__)


class LLMUnavailableError(Exception):
    """The configured LLM could not be reached or returned an unusable response."""


class LLMClient(Protocol):
    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        """Runs a single structured-output completion call and returns the parsed JSON
        object. Raises `LLMUnavailableError` on any failure — never returns a partial/None
        result.
        """
        ...


class OpenAICompatibleClient:
    """Targets `{base_url}/chat/completions` with `response_format: json_object` — the
    OpenAI-compatible shape LM Studio/Ollama/vLLM (and OpenAI itself) all implement.
    """

    def __init__(self, *, base_url: str, model: str, api_key: str | None, timeout_s: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout_s = timeout_s
        self.total_tokens_used: int | None = None

    @property
    def provider(self) -> str:
        return "openai_compatible"

    @property
    def model(self) -> str:
        return self._model

    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as http_client:
                response = await http_client.post(
                    f"{self._base_url}/chat/completions", json=payload, headers=headers
                )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            usage_tokens = body.get("usage", {}).get("total_tokens")
            if isinstance(usage_tokens, int):
                self.total_tokens_used = (self.total_tokens_used or 0) + usage_tokens
            return dict(json.loads(content))
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(f"LLM endpoint unreachable: {exc}") from exc
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailableError(f"LLM response missing expected shape: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise LLMUnavailableError(f"LLM response content was not valid JSON: {exc}") from exc


async def build_llm_client(
    db: AsyncSession, settings: Settings | None = None
) -> LLMClient | None:
    """Reads connection details from dynamic config (issue #30's `llm.*` keys, falling back
    to env defaults), and builds a client for it.

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

    base_url = await get_config_value(db, "llm.base_url", settings.llm_base_url)
    model = await get_config_value(db, "llm.model", settings.llm_model)
    if not base_url or not model:
        return None

    api_key = await get_secret_config_value(db, "llm.api_key") or settings.llm_api_key
    timeout_s = await get_config_value(db, "llm.timeout_s", settings.llm_timeout_s)
    return OpenAICompatibleClient(
        base_url=str(base_url), model=str(model), api_key=api_key, timeout_s=float(timeout_s)
    )
