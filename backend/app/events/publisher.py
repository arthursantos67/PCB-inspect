"""Publishes inspection pipeline events (FR-14) to the Redis pub/sub channel
(`events:inspections`, section 3.6) that the SSE endpoint (`app.events.sse`) subscribes to.

Best-effort, mirroring `app.inference.status`: a Redis hiccup here must never fail ingestion
or pipeline processing — only real-time delivery, which the frontend's polling fallback
(FR-04's `GET /api/v1/inspections/{id}`) covers regardless.

A fresh client per call, rather than a module-level singleton, mirrors `app.tasks.db`'s
`NullPool` rationale: call sites span both the API's long-lived event loop and each Celery
task's own throwaway `asyncio.run()` loop, and a redis-py async client is bound to whichever
loop first uses it.
"""

import json
import logging
from typing import Any, Literal

from redis.asyncio import Redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

CHANNEL = "events:inspections"

EventType = Literal[
    "inspection.created",
    "detection.completed",
    "analysis.completed",
    "inspection.failed",
    "report.completed",
    "report.failed",
    "dataset_export.completed",
    "dataset_export.failed",
]


async def publish_event(event_type: EventType, data: dict[str, Any]) -> None:
    try:
        client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
        try:
            message = json.dumps({"event": event_type, "data": data}, default=str)
            await client.publish(CHANNEL, message)
        finally:
            await client.aclose()
    except Exception:  # noqa: BLE001 — see module docstring
        logger.warning("Failed to publish %s event to Redis", event_type, exc_info=True)
