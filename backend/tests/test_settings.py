"""Dynamic system configuration tests (FR-13).

Issue #21 item 8 covered `SystemConfig` values marked `is_secret` (cloud LLM API keys) being
genuinely encrypted at rest and never returned in cleartext by `GET /api/v1/settings/config`.
Issue #30 extends the allowed key set to cover every FR-13 value (LLM connection, agent
analysis policy, quality alert thresholds, retention, reports directory) with per-key
validation, and adds a regression test that the expanded key set doesn't widen what's secret.
"""

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import InvalidToken, decrypt_secret, encrypt_secret
from app.models import SystemConfig
from app.settings.service import get_secret_config_value

ACCOUNT = {
    "email": "operator@pcb-inspect.local",
    "password": "correct-horse-battery",
    "full_name": "Operator",
}

SECRET_API_KEY = "sk-super-secret-value-12345"


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _setup_account(client: AsyncClient) -> str:
    response = await client.post("/api/v1/auth/setup", json=ACCOUNT)
    return response.json()["access_token"]


async def test_secret_config_value_is_never_returned_in_cleartext(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)

    patch_response = await client.patch(
        "/api/v1/settings/config",
        json={"config": {"llm.api_key": SECRET_API_KEY}},
        headers=_auth_headers(token),
    )
    assert patch_response.status_code == 200
    patched = patch_response.json()["config"]["llm.api_key"]
    assert patched == {"configured": True, "last4": "2345"}
    assert SECRET_API_KEY not in patch_response.text

    get_response = await client.get("/api/v1/settings/config", headers=_auth_headers(token))
    assert get_response.status_code == 200
    assert get_response.json()["config"]["llm.api_key"] == {"configured": True, "last4": "2345"}
    assert SECRET_API_KEY not in get_response.text


async def test_secret_config_value_is_encrypted_at_rest(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    await client.patch(
        "/api/v1/settings/config",
        json={"config": {"llm.api_key": SECRET_API_KEY}},
        headers=_auth_headers(token),
    )

    row = await db_session.get(SystemConfig, "llm.api_key")
    assert row is not None
    assert row.is_secret is True
    ciphertext = row.value["ciphertext"]
    assert ciphertext is not None
    assert SECRET_API_KEY not in ciphertext
    assert decrypt_secret(get_settings(), ciphertext) == SECRET_API_KEY


async def test_get_secret_config_value_decrypts_for_internal_use(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    await client.patch(
        "/api/v1/settings/config",
        json={"config": {"llm.api_key": SECRET_API_KEY}},
        headers=_auth_headers(token),
    )

    assert await get_secret_config_value(db_session, "llm.api_key") == SECRET_API_KEY


async def test_clearing_secret_config_value_reports_not_configured(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    await client.patch(
        "/api/v1/settings/config",
        json={"config": {"llm.api_key": SECRET_API_KEY}},
        headers=_auth_headers(token),
    )

    clear_response = await client.patch(
        "/api/v1/settings/config",
        json={"config": {"llm.api_key": ""}},
        headers=_auth_headers(token),
    )

    assert clear_response.json()["config"]["llm.api_key"] == {"configured": False, "last4": None}
    assert await get_secret_config_value(db_session, "llm.api_key") is None


async def test_non_secret_config_key_is_unaffected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Regression guard: only the secret-key allowlist goes through encryption — existing keys
    (e.g. `watch_mode_enabled`) must keep round-tripping as plain scalars.
    """
    token = await _setup_account(client)
    response = await client.patch(
        "/api/v1/settings/config",
        json={"config": {"watch_mode_enabled": False}},
        headers=_auth_headers(token),
    )

    assert response.json()["config"]["watch_mode_enabled"] is False
    row = await db_session.get(SystemConfig, "watch_mode_enabled")
    assert row is not None
    assert row.is_secret is False
    assert row.value is False


async def test_confidence_threshold_outside_range_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)

    response = await client.patch(
        "/api/v1/settings/config",
        json={"config": {"min_confidence_report": 1.5}},
        headers=_auth_headers(token),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CONFIG_INVALID_VALUE"
    assert await db_session.get(SystemConfig, "min_confidence_report") is None


async def test_unknown_provider_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)

    response = await client.patch(
        "/api/v1/settings/config",
        json={"config": {"llm.provider": "not-a-real-provider"}},
        headers=_auth_headers(token),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CONFIG_INVALID_VALUE"
    assert await db_session.get(SystemConfig, "llm.provider") is None


async def test_unknown_config_key_is_rejected(client: AsyncClient) -> None:
    token = await _setup_account(client)

    response = await client.patch(
        "/api/v1/settings/config",
        json={"config": {"totally_made_up_key": "value"}},
        headers=_auth_headers(token),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CONFIG_UNKNOWN_KEY"


async def test_invalid_key_in_batch_rejects_the_whole_update(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """One bad key in a multi-key `PATCH` must reject atomically — a valid key alongside it
    must not be silently persisted while the bad one is rejected.
    """
    token = await _setup_account(client)

    response = await client.patch(
        "/api/v1/settings/config",
        json={"config": {"min_confidence_store": 0.3, "agent_analysis_mode": "not-a-mode"}},
        headers=_auth_headers(token),
    )

    assert response.status_code == 422
    assert await db_session.get(SystemConfig, "min_confidence_store") is None


async def test_agent_analysis_trigger_criteria_are_configurable(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """FR-06's conditional-mode trigger criteria (N+ defects, a critical class, min severity) —
    prerequisite config surface for issue #16's agent chain, not yet consumed here.
    """
    token = await _setup_account(client)

    response = await client.patch(
        "/api/v1/settings/config",
        json={
            "config": {
                "agent_analysis_mode": "conditional",
                "agent_analysis_min_defect_count": 3,
                "agent_analysis_critical_classes": ["short", "open_circuit"],
                "agent_analysis_min_severity": "high",
            }
        },
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    config = response.json()["config"]
    assert config["agent_analysis_min_defect_count"] == 3
    assert config["agent_analysis_critical_classes"] == ["short", "open_circuit"]


async def test_agent_analysis_critical_classes_rejects_unknown_defect_type(
    client: AsyncClient,
) -> None:
    token = await _setup_account(client)

    response = await client.patch(
        "/api/v1/settings/config",
        json={"config": {"agent_analysis_critical_classes": ["not_a_defect_type"]}},
        headers=_auth_headers(token),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CONFIG_INVALID_VALUE"


async def test_quality_alert_thresholds_are_configurable(client: AsyncClient) -> None:
    token = await _setup_account(client)

    response = await client.patch(
        "/api/v1/settings/config",
        json={
            "config": {"alert_defect_rate_threshold": 0.15, "alert_window_minutes": 60}
        },
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    config = response.json()["config"]
    assert config["alert_defect_rate_threshold"] == 0.15
    assert config["alert_window_minutes"] == 60


async def test_alert_window_minutes_rejects_zero(client: AsyncClient) -> None:
    token = await _setup_account(client)

    response = await client.patch(
        "/api/v1/settings/config",
        json={"config": {"alert_window_minutes": 0}},
        headers=_auth_headers(token),
    )

    assert response.status_code == 422


async def test_retention_days_is_configurable(client: AsyncClient) -> None:
    token = await _setup_account(client)

    response = await client.patch(
        "/api/v1/settings/config",
        json={"config": {"retention_days": 730}},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json()["config"]["retention_days"] == 730


async def test_reports_output_dir_is_created_and_configurable(
    client: AsyncClient, tmp_path: Path
) -> None:
    token = await _setup_account(client)
    target = tmp_path / "reports"
    assert not target.exists()

    response = await client.patch(
        "/api/v1/settings/config",
        json={"config": {"reports_output_dir": str(target)}},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json()["config"]["reports_output_dir"] == str(target)
    assert target.is_dir()


async def test_new_secret_eligible_keys_never_round_trip_in_cleartext(
    client: AsyncClient,
) -> None:
    """Regression guard for issue #30's expanded key set (AC 4): only `llm.api_key` is
    `is_secret` — the other new LLM keys (`llm.provider`, `llm.base_url`, `llm.model`,
    `llm.timeout_s`) must keep round-tripping as plain values, same as before this issue.
    """
    token = await _setup_account(client)

    response = await client.patch(
        "/api/v1/settings/config",
        json={
            "config": {
                "llm.provider": "openai_compatible",
                "llm.base_url": "http://localhost:1234/v1",
                "llm.model": "local-model",
                "llm.timeout_s": 30,
            }
        },
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    config = response.json()["config"]
    assert config["llm.provider"] == "openai_compatible"
    assert config["llm.base_url"] == "http://localhost:1234/v1"
    assert config["llm.model"] == "local-model"
    assert config["llm.timeout_s"] == 30


def test_decrypting_with_wrong_key_fails() -> None:
    settings = get_settings()
    token = encrypt_secret(settings, "some-secret")
    wrong_settings = settings.model_copy(update={"secret_key": "a-completely-different-key"})
    with pytest.raises(InvalidToken):
        decrypt_secret(wrong_settings, token)
