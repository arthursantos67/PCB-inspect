"""Per-role endpoint resolution (`app.agents.llm_client.resolve_llm_connection`).

The rule under test is the precedence chain, applied per *field* rather than per role:

    role in dynamic config -> role in env -> global in dynamic config -> global in env

Per-field is the part worth pinning down. It is what lets a station override only
`llm.chat.model` and keep inheriting the shared `llm.base_url`/`llm.api_key`, and equally what
lets one role move to a different provider entirely without the other two having to be
respelled. A per-*role* fallback would silently break the first case by sending the overridden
chat model to whatever base_url the role block failed to mention.

`SystemConfig` rows are seeded directly rather than through `update_config`, which needs an
actor for the audit trail — the same convention tests/test_health.py uses.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_client import build_llm_client, resolve_llm_connection
from app.core.config import Settings
from app.models import SystemConfig
from app.settings.service import _encrypt_for_storage


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "llm_base_url": "http://global.invalid/v1",
        "llm_model": "global-model",
        "llm_api_key": "global-key",
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


async def _seed(db: AsyncSession, key: str, value: object) -> None:
    db.add(SystemConfig(key=key, value=value, is_secret=False))
    await db.flush()


async def _seed_secret(db: AsyncSession, key: str, plaintext: str) -> None:
    db.add(SystemConfig(key=key, value=_encrypt_for_storage(plaintext), is_secret=True))
    await db.flush()


@pytest.mark.asyncio
async def test_role_falls_back_to_globals_when_nothing_scoped_is_set(
    db_session: AsyncSession,
) -> None:
    """The single-endpoint station: no role config anywhere, so every role resolves to the
    same globals the pre-split code used.
    """
    for role in ("chat", "analysis", "report"):
        connection = await resolve_llm_connection(db_session, _settings(), role)  # type: ignore[arg-type]
        assert connection.base_url == "http://global.invalid/v1"
        assert connection.model == "global-model"
        assert connection.api_key == "global-key"


@pytest.mark.asyncio
async def test_role_env_overrides_global_config(db_session: AsyncSession) -> None:
    """Role-level env beats a *database* global. This is the ordering that actually matters in
    production: the station has stale `llm.base_url`/`llm.model` rows in `system_config` from
    the local-model era, and pointing a role at a hosted endpoint through .env has to win
    without anyone first having to clear those rows by hand.
    """
    await _seed(db_session, "llm.base_url", "http://stale-db.invalid/v1")

    connection = await resolve_llm_connection(
        db_session,
        _settings(llm_chat_base_url="https://chat.invalid/v1", llm_chat_model="chat-model"),
        "chat",
    )

    assert connection.base_url == "https://chat.invalid/v1"
    assert connection.model == "chat-model"


@pytest.mark.asyncio
async def test_role_config_overrides_role_env(db_session: AsyncSession) -> None:
    """Dynamic config is the most specific source, so the Settings screen always wins over a
    value baked into the environment at container start.
    """
    await _seed(db_session, "llm.chat.model", "from-db")

    connection = await resolve_llm_connection(
        db_session, _settings(llm_chat_model="from-env"), "chat"
    )

    assert connection.model == "from-db"


@pytest.mark.asyncio
async def test_fallback_is_per_field_not_per_role(db_session: AsyncSession) -> None:
    """A role that overrides only the model keeps inheriting the global base_url and key."""
    await _seed(db_session, "llm.report.model", "openai/gpt-oss-120b")

    connection = await resolve_llm_connection(db_session, _settings(), "report")

    assert connection.model == "openai/gpt-oss-120b"
    assert connection.base_url == "http://global.invalid/v1"
    assert connection.api_key == "global-key"


@pytest.mark.asyncio
async def test_roles_resolve_independently(db_session: AsyncSession) -> None:
    """The whole point of the split: three roles, two providers, one process."""
    settings = _settings(
        llm_chat_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        llm_chat_model="gemini-2.5-flash-lite",
        llm_chat_api_key="google-key",
        llm_analysis_base_url="https://api.groq.com/openai/v1",
        llm_analysis_model="qwen/qwen3.6-27b",
        llm_analysis_api_key="groq-key",
        llm_report_base_url="https://api.groq.com/openai/v1",
        llm_report_model="openai/gpt-oss-120b",
        llm_report_api_key="groq-key",
    )

    chat = await resolve_llm_connection(db_session, settings, "chat")
    analysis = await resolve_llm_connection(db_session, settings, "analysis")
    report = await resolve_llm_connection(db_session, settings, "report")

    assert chat.model == "gemini-2.5-flash-lite"
    assert chat.api_key == "google-key"
    assert analysis.model == "qwen/qwen3.6-27b"
    assert report.model == "openai/gpt-oss-120b"
    assert analysis.base_url == report.base_url == "https://api.groq.com/openai/v1"
    assert chat.base_url != analysis.base_url


@pytest.mark.asyncio
async def test_role_none_resolves_globals(db_session: AsyncSession) -> None:
    """`role=None` is the pre-split behaviour, and must ignore role config entirely — callers
    that never opted into a role must not start picking one up by accident.
    """
    await _seed(db_session, "llm.chat.model", "chat-only")

    connection = await resolve_llm_connection(db_session, _settings(), None)

    assert connection.model == "global-model"


@pytest.mark.asyncio
async def test_role_api_key_is_stored_encrypted_and_resolves(db_session: AsyncSession) -> None:
    """The three new `*.api_key` keys are secrets like `llm.api_key`: written through the
    encrypting path and read back only by `get_secret_config_value`.
    """
    await _seed_secret(db_session, "llm.analysis.api_key", "gsk-secret-value")

    connection = await resolve_llm_connection(db_session, _settings(), "analysis")

    assert connection.api_key == "gsk-secret-value"


@pytest.mark.asyncio
async def test_build_llm_client_uses_the_requested_role(db_session: AsyncSession) -> None:
    settings = _settings(
        llm_chat_base_url="https://chat.invalid/v1",
        llm_chat_model="chat-model",
        llm_report_base_url="https://report.invalid/v1",
        llm_report_model="report-model",
    )

    chat_client = await build_llm_client(db_session, settings, role="chat")
    report_client = await build_llm_client(db_session, settings, role="report")

    assert chat_client is not None and chat_client.model == "chat-model"
    assert report_client is not None and report_client.model == "report-model"


@pytest.mark.asyncio
async def test_reasoning_effort_resolves_per_role(db_session: AsyncSession) -> None:
    """`reasoning_effort` follows the same per-field chain as the rest, and it has to: it is a
    property of the *model*, and the whole point of the split is that the three roles can run
    different models. Groq's qwen3.6 needs `none` for structured output while its gpt-oss does
    not, so a single global value would break one of the two.
    """
    settings = _settings(llm_analysis_reasoning_effort="none", llm_reasoning_effort="default")

    analysis = await resolve_llm_connection(db_session, settings, "analysis")
    report = await resolve_llm_connection(db_session, settings, "report")

    assert analysis.reasoning_effort == "none"
    assert report.reasoning_effort == "default"


@pytest.mark.asyncio
async def test_reasoning_effort_is_none_when_unset_anywhere(db_session: AsyncSession) -> None:
    """Unset must stay unset all the way to the payload — the local-first default endpoint
    would be sent a field it does not implement otherwise.
    """
    connection = await resolve_llm_connection(db_session, _settings(), "chat")

    assert connection.reasoning_effort is None
