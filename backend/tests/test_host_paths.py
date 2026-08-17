"""Host-path translation and the watch-root folder picker.

The watch root used to be pinned to the one directory pre-mounted in `docker-compose.yml`, so
pointing it anywhere else meant editing `.env` and restarting the stack. The host filesystem is
now bind-mounted read-only and paths are translated onto that mount at the filesystem boundary,
which is what these cover: the operator enters a host path, the container opens the mounted one,
and everything reported back names the host path again.
"""

from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.host_paths import to_container_path, to_host_path
from app.main import app as fastapi_app
from app.settings import service as settings_service

ACCOUNT = {
    "email": "operator@pcb-inspect.local",
    "password": "correct-horse-battery",
    "full_name": "Operator",
}


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _setup_account(client: AsyncClient) -> str:
    response = await client.post("/api/v1/auth/setup", json=ACCOUNT)
    return response.json()["access_token"]


@pytest.fixture
def host_mount(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Stands in for the compose bind mount: `host_root` is the operator's view of a directory
    tree, `mount` is where the container sees it. Both point at the same real files here, which
    is enough to exercise the translation without needing an actual container.
    """
    host_root = tmp_path / "host"
    host_root.mkdir()
    overridden = get_settings().model_copy(
        update={"host_fs_root": str(host_root), "host_fs_mount": str(host_root)}
    )
    monkeypatch.setattr("app.core.host_paths.get_settings", lambda: overridden)
    monkeypatch.setattr("app.settings.service.get_settings", lambda: overridden)
    fastapi_app.dependency_overrides[get_settings] = lambda: overridden
    yield host_root
    fastapi_app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def whole_host_mounted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The production shape: the whole host filesystem (`/`) mounted somewhere inside the
    container. `tmp_path` stands in for that mount point because translation only kicks in when
    the mount really exists on disk.
    """
    mount = tmp_path / "hostfs"
    mount.mkdir()
    overridden = get_settings().model_copy(
        update={"host_fs_root": "/", "host_fs_mount": str(mount)}
    )
    monkeypatch.setattr("app.core.host_paths.get_settings", lambda: overridden)
    return mount


def test_host_path_translates_onto_the_mount(whole_host_mounted: Path) -> None:
    assert to_container_path("/home/op/PCB_Test") == whole_host_mounted / "home/op/PCB_Test"
    assert to_host_path(whole_host_mounted / "home/op/PCB_Test") == Path("/home/op/PCB_Test")


def test_container_owned_and_already_mounted_paths_are_left_alone(
    whole_host_mounted: Path,
) -> None:
    """Rows ingested before the host mount existed still carry `/data/watch-root/...`, and a
    path already inside the mount must not be translated a second time.
    """
    assert to_container_path("/data/watch-root/BATCH-1") == Path("/data/watch-root/BATCH-1")
    assert to_container_path(whole_host_mounted / "home/op") == whole_host_mounted / "home/op"


def test_translation_is_a_no_op_when_nothing_is_mounted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The backend running directly on the host, rather than in a container — host paths are
    already openable as they are, so translating them would break every one of them.
    """
    overridden = get_settings().model_copy(
        update={"host_fs_root": "/", "host_fs_mount": "/nonexistent-mount"}
    )
    monkeypatch.setattr("app.core.host_paths.get_settings", lambda: overridden)

    assert to_container_path("/home/op/PCB_Test") == Path("/home/op/PCB_Test")
    assert to_host_path("/home/op/PCB_Test") == Path("/home/op/PCB_Test")


async def test_watch_root_accepts_any_host_folder(client: AsyncClient, host_mount: Path) -> None:
    token = await _setup_account(client)
    (host_mount / "Documents" / "PCB_Test").mkdir(parents=True)

    response = await client.patch(
        "/api/v1/settings/config",
        json={"config": {"watch_root_path": str(host_mount / "Documents" / "PCB_Test")}},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    stored = response.json()["config"]["watch_root_path"]
    # Stored as the host path the operator entered, not the container's translated view.
    assert stored == str(host_mount / "Documents" / "PCB_Test")


async def test_browse_lists_subdirectories_of_a_host_folder(
    client: AsyncClient, host_mount: Path
) -> None:
    token = await _setup_account(client)
    (host_mount / "Documents").mkdir()
    (host_mount / "Pictures").mkdir()
    (host_mount / ".cache").mkdir()
    (host_mount / "notes.txt").write_text("not a directory")

    response = await client.get(
        "/api/v1/settings/browse",
        params={"path": str(host_mount)},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert [entry["name"] for entry in body["directories"]] == ["Documents", "Pictures"]
    assert body["parent"] is None  # already at the browsable root


async def test_browse_rejects_a_path_outside_the_browsable_root(
    client: AsyncClient, host_mount: Path
) -> None:
    """Otherwise an untranslated path would list the container's own filesystem."""
    token = await _setup_account(client)

    response = await client.get(
        "/api/v1/settings/browse", params={"path": "/etc"}, headers=_auth_headers(token)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PATH_NOT_FOUND"


async def test_browse_rejects_a_path_that_escapes_the_root_with_dot_dot(
    client: AsyncClient, host_mount: Path
) -> None:
    """`is_relative_to` is a lexical comparison: `<root>/../secret` satisfies a guard rooted at
    `<root>` while the filesystem resolves it outside the mount. The path is normalized before
    anything compares or opens it (`app.core.host_paths.normalize_host_path`).
    """
    token = await _setup_account(client)
    outside = host_mount.parent / "outside-the-root"
    outside.mkdir()
    (outside / "private-stuff").mkdir()

    response = await client.get(
        "/api/v1/settings/browse",
        params={"path": f"{host_mount}/../{outside.name}"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PATH_NOT_FOUND"


async def test_a_watch_root_with_dot_dot_is_stored_normalized(
    client: AsyncClient, host_mount: Path
) -> None:
    """Same reason, on the way in: a stored path carrying `..` would defeat the containment
    check on every later scan, not just on the request that saved it.
    """
    token = await _setup_account(client)
    (host_mount / "Documents" / "PCB_Test").mkdir(parents=True)

    response = await client.patch(
        "/api/v1/settings/config",
        json={"config": {"watch_root_path": f"{host_mount}/Documents/../Documents/PCB_Test"}},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json()["config"]["watch_root_path"] == str(
        host_mount / "Documents" / "PCB_Test"
    )


async def test_browse_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/settings/browse")
    assert response.status_code == 401


async def test_list_directories_defaults_to_the_browsable_root(host_mount: Path) -> None:
    (host_mount / "Documents").mkdir()

    listing = await settings_service.list_directories(None)

    assert listing.path == str(host_mount)
    assert [entry.name for entry in listing.directories] == ["Documents"]
