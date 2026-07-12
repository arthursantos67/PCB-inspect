"""Dynamic system configuration tests (FR-13), focused on issue #21 item 8: `SystemConfig`
values marked `is_secret` (cloud LLM API keys) must be genuinely encrypted at rest and never
returned in cleartext by `GET /api/v1/settings/config` — previously `is_secret` was never set
by any reachable path and nothing encrypted the stored value at all.
"""

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


def test_decrypting_with_wrong_key_fails() -> None:
    settings = get_settings()
    token = encrypt_secret(settings, "some-secret")
    wrong_settings = settings.model_copy(update={"secret_key": "a-completely-different-key"})
    with pytest.raises(InvalidToken):
        decrypt_secret(wrong_settings, token)
