"""Cross-process publication of the inference worker's warm-start state (RV-01/RV-02).

The loaded model lives inside the `worker-inference` Celery process; the API's `/health`
endpoint (FR-15) runs in a different process entirely and has no direct handle to it. Redis
is already the shared broker/cache for this stack (section 3.6), so a small status key is a
lighter mechanism here than adding a Celery remote-control round trip: the worker writes it
once after a successful load, and `/health` just reads it back.
"""

import json
import logging
from datetime import UTC, datetime
from typing import TypedDict

from redis.asyncio import Redis

from app.core.config import Settings

_STATUS_KEY = "inference:worker_status"


class ModelStatus(TypedDict):
    model_loaded: bool
    device: str
    model_version: str
    updated_at: str


async def publish_model_status(settings: Settings, *, device: str, model_version: str) -> None:
    """Best-effort: this is purely for `/health` observability, not correctness — a Redis
    hiccup here must never fail the model load itself (RV-01) or the inference task using it.
    """
    try:
        client = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        try:
            payload: ModelStatus = {
                "model_loaded": True,
                "device": device,
                "model_version": model_version,
                "updated_at": datetime.now(UTC).isoformat(),
            }
            await client.set(_STATUS_KEY, json.dumps(payload))
        finally:
            await client.aclose()
    except Exception:  # noqa: BLE001 — see docstring
        logging.getLogger(__name__).warning(
            "Failed to publish model status to Redis", exc_info=True
        )


async def get_model_status(settings: Settings) -> ModelStatus | None:
    """Returns `None` on any Redis error or if nothing has published a status yet — the
    caller (health check) treats that the same as "not loaded", never as a hard failure.
    """
    try:
        client = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        try:
            raw = await client.get(_STATUS_KEY)
        finally:
            await client.aclose()
    except Exception:  # noqa: BLE001 — health check must never raise
        return None
    if raw is None:
        return None
    status: ModelStatus = json.loads(raw)
    return status
