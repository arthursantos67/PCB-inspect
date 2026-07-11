"""Redis-backed cache for dashboard aggregates (FR-08, PRD section 3.6: key
`stats:{name}:{...}`, TTL 60s). Mirrors `app.events.publisher`/`app.inference.status`'s
fresh-client-per-call pattern — see those modules' docstrings for why no module-level
singleton is used here either.

Unlike those best-effort *write* paths, a cache *read* failure here must fall through to
recomputing from the database rather than being treated as "permanently uncached": callers
treat `get_cached() is None` as "compute me", whether that's a real miss, TTL expiry, or a
Redis hiccup.
"""

import json
import logging
from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60


async def get_cached(key: str) -> Any | None:
    try:
        client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
        try:
            raw = await client.get(key)
        finally:
            await client.aclose()
    except Exception:  # noqa: BLE001 — see module docstring
        logger.warning("Failed to read stats cache key %s", key, exc_info=True)
        return None
    if raw is None:
        return None
    return json.loads(raw)


async def set_cached(key: str, value: Any, ttl: int = CACHE_TTL_SECONDS) -> None:
    try:
        client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
        try:
            await client.set(key, json.dumps(value, default=str), ex=ttl)
        finally:
            await client.aclose()
    except Exception:  # noqa: BLE001 — see module docstring
        logger.warning("Failed to write stats cache key %s", key, exc_info=True)


async def invalidate_all() -> None:
    """Called by the pipeline (`app.tasks.pipeline`) after an image reaches `COMPLETED` so a
    dashboard refetch triggered by the SSE event that accompanies it (FE-09) doesn't serve a
    stale aggregate for up to the full TTL — best-effort like every other operation here: a
    failed invalidation just means the *next* GET still recomputes once the TTL naturally
    lapses, per PRD section 3.6.
    """
    try:
        client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
        try:
            keys = [key async for key in client.scan_iter(match="stats:*")]
            if keys:
                await client.delete(*keys)
        finally:
            await client.aclose()
    except Exception:  # noqa: BLE001 — see module docstring
        logger.warning("Failed to invalidate stats cache", exc_info=True)
