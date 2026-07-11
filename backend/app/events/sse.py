"""Authenticated SSE stream (FR-14, section 3.6): forwards messages published by
`app.events.publisher` on Redis pub/sub to connected clients as they arrive.

Session-token authenticated like every other endpoint (`get_current_user`, section 13) —
native `EventSource` can't send an `Authorization` header, so the frontend hook (FE-09,
`useEventStream`) opens this with `fetch()` and a manual SSE line reader instead.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis

from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.events.publisher import CHANNEL
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/events", tags=["events"])

# Keeps idle connections alive through intermediary proxies/load balancers and gives the
# generator a regular point at which to notice the client has disconnected — the poll
# timeout below is what actually bounds that latency, not this interval.
_HEARTBEAT_INTERVAL_S = 15.0
_POLL_TIMEOUT_S = 1.0


async def _event_stream(request: Request) -> AsyncIterator[str]:
    client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
    pubsub = client.pubsub()
    await pubsub.subscribe(CHANNEL)
    loop = asyncio.get_event_loop()
    last_sent = loop.time()
    try:
        while True:
            if await request.is_disconnected():
                break
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=_POLL_TIMEOUT_S
            )
            if message is not None:
                raw = message["data"]
                raw_str = raw.decode() if isinstance(raw, bytes) else raw
                envelope = json.loads(raw_str)
                data = json.dumps(envelope["data"], default=str)
                yield f"event: {envelope['event']}\ndata: {data}\n\n"
                last_sent = loop.time()
                continue
            now = loop.time()
            if now - last_sent >= _HEARTBEAT_INTERVAL_S:
                yield ": keep-alive\n\n"
                last_sent = now
    finally:
        await pubsub.unsubscribe(CHANNEL)
        await pubsub.aclose()
        await client.aclose()


@router.get("")
async def stream_events(
    request: Request,
    _current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
