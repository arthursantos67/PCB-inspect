"""Translation between host paths and the container's read-only view of them.

The operator picks a folder on their own machine (`/home/op/Documents/PCB_Test`), but the
backend runs inside a container where that path only exists under the host filesystem mount
(`/hostfs/home/op/Documents/PCB_Test`). Without this, the watch root could only ever be the
one folder pre-mounted in `docker-compose.yml`, and changing it meant editing `.env` and
restarting the stack — which FR-20's terminal-free operation rules out.

Host paths are what the operator sees and what `watch_root_path` stores; container paths are
what any filesystem call must use. Nothing else in the app should hardcode the mount prefix.
"""

import os
from functools import lru_cache
from pathlib import Path, PurePosixPath

from app.core.config import get_settings

# Paths the container owns outright — already real inside the container, never translated.
_CONTAINER_OWNED = (PurePosixPath("/data"), PurePosixPath("/weights"))


def normalize_host_path(host_path: Path | str) -> PurePosixPath:
    """An operator-supplied host path with `.` and `..` segments collapsed away.

    Every containment check in the app (`is_relative_to` against `HOST_FS_ROOT`, and the mount
    translation below) is lexical, so `/home/../etc` would otherwise pass a guard on `/home`
    and then be resolved by the *filesystem* into the container's own `/etc`. `..` has no
    legitimate meaning in a path the operator picked from a folder browser, so it is removed
    before anything compares or opens it. Purely lexical on purpose: it must not touch the
    filesystem, since a host path is generally not openable under that name from here.
    """
    return PurePosixPath(os.path.normpath(str(PurePosixPath(host_path))))


@lru_cache(maxsize=8)
def _mount_if_present(mount: str) -> PurePosixPath | None:
    """`None` when nothing is actually mounted there — the backend is running directly on the
    host (dev, tests, or a non-Docker deployment) and host paths are already openable as-is.
    """
    if not mount or not Path(mount).is_dir():
        return None
    return PurePosixPath(mount)


def _mount() -> PurePosixPath | None:
    return _mount_if_present(get_settings().host_fs_mount)


def _root() -> PurePosixPath:
    return PurePosixPath(get_settings().host_fs_root or "/")


def to_container_path(host_path: Path | str) -> Path:
    """The path to actually open, for an operator-supplied host path.

    Returns the input unchanged when there is no host mount configured, when the path is
    already container-owned (`/data/...`, e.g. rows ingested before the mount existed), or
    when it already points into the mount.
    """
    path = normalize_host_path(host_path)
    mount = _mount()
    if mount is None or not path.is_absolute():
        return Path(path)
    if path == mount or path.is_relative_to(mount):
        return Path(path)
    if any(path == owned or path.is_relative_to(owned) for owned in _CONTAINER_OWNED):
        return Path(path)

    root = _root()
    if not path.is_relative_to(root):
        # Outside the mounted subtree — left alone so the caller's own existence check reports
        # it, rather than silently resolving to an unrelated path inside the mount.
        return Path(path)
    return Path(mount / path.relative_to(root))


def to_host_path(container_path: Path | str) -> Path:
    """Inverse of `to_container_path`, for displaying a path back to the operator."""
    path = PurePosixPath(container_path)
    mount = _mount()
    if mount is None or not path.is_relative_to(mount):
        return Path(path)
    return Path(_root() / path.relative_to(mount))
