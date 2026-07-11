"""GET /api/v1/events (FR-14, PRD section 3.6) — authenticated SSE stream backed by Redis
pub/sub (`events:inspections`). Requires a reachable Redis (see the `redis` service in CI's
`backend-test` job and `REDIS_URL` locally).

Auth is exercised over real HTTP (the 401 path returns before the stream ever opens, so it's
safe under httpx's `ASGITransport`). Delivery is exercised against `_event_stream` directly
instead: `ASGITransport`/Starlette's `TestClient` both drive the whole ASGI app call to
completion before handing back *any* response — including headers — which deadlocks against
an intentionally never-ending generator like this one (it only exits on client disconnect).
Calling the generator directly sidesteps that transport limitation while still exercising the
real Redis-subscribe -> SSE-line code path the endpoint uses.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.events.publisher import publish_event
from app.events.sse import _event_stream
from app.inference.detect import RawDetection
from app.ingestion import service as ingestion_service
from app.models import ModelVersion
from app.models.enums import ImageSource
from app.tasks.pipeline import run_inference

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


class _FakeYOLO:
    """Stands in for `ultralytics.YOLO` — never touches real weights (mirrors
    tests/test_pipeline_tasks.py's stub of the same name).
    """

    def __init__(self, weights_path: str) -> None:
        self.weights_path = weights_path

    def to(self, device: str) -> "_FakeYOLO":
        self.device = device
        return self


class _NeverDisconnectedRequest:
    """Minimal stand-in for the `Request` the endpoint only uses for `is_disconnected()`."""

    async def is_disconnected(self) -> bool:
        return False


class _NoOpInferenceTask:
    """Stands in for the real Celery `.delay()` — there's no broker in this test environment
    (mirrors tests/test_ingestion.py's `enqueue_stub`); `run_inference.apply()` is called
    directly below to simulate the worker instead.
    """

    def delay(self, inspection_image_id: str) -> None:
        return None


def _parse_sse_chunk(chunk: str) -> dict:
    event_type = None
    data = None
    for line in chunk.split("\n"):
        if line.startswith("event:"):
            event_type = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data = json.loads(line[len("data:") :].strip())
    assert event_type is not None
    return {"event": event_type, "data": data}


async def _collect_chunks(generator: AsyncIterator[str], count: int) -> list[str]:
    chunks: list[str] = []
    async for chunk in generator:
        if chunk.startswith(": keep-alive"):
            continue
        chunks.append(chunk)
        if len(chunks) >= count:
            return chunks
    return chunks


# --- Auth (exercised over real HTTP — the 401 path never enters the stream) -------------------


async def test_unauthenticated_client_cannot_open_stream(client: AsyncClient) -> None:
    response = await client.get("/api/v1/events")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


# --- Delivery (exercised directly against the generator, see module docstring) ----------------


async def test_stream_forwards_a_published_event() -> None:
    generator = _event_stream(_NeverDisconnectedRequest())
    collector = asyncio.ensure_future(_collect_chunks(generator, count=1))
    await asyncio.sleep(0.3)  # let the Redis subscription establish before publishing
    try:
        await publish_event("inspection.created", {"id": "abc-123", "status": "QUEUED"})
        chunks = await asyncio.wait_for(collector, timeout=5)
    finally:
        await generator.aclose()

    assert [_parse_sse_chunk(c) for c in chunks] == [
        {"event": "inspection.created", "data": {"id": "abc-123", "status": "QUEUED"}}
    ]


async def test_event_delivery_sequence_for_a_processed_image(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UC-4 end to end, observed over the pub/sub channel the SSE endpoint reads from:
    ingesting a file that triggers a reportable detection emits `inspection.created`
    (ingestion), then `detection.completed` and `analysis.completed` (the pipeline task) —
    in that order.
    """
    model_version = ModelVersion(version="v1.0.0", weights_path="/weights/best.pt", is_active=True)
    db_session.add(model_version)
    await db_session.commit()

    monkeypatch.setattr(ingestion_service, "run_inference", _NoOpInferenceTask())

    bbox = {"x1": 0.1, "y1": 0.1, "x2": 0.5, "y2": 0.5}
    monkeypatch.setattr("app.inference.model._yolo_class", lambda: _FakeYOLO)
    monkeypatch.setattr(
        "app.inference.service.detect",
        lambda *args, **kwargs: [RawDetection(defect_type="mouse_bite", confidence=0.9, bbox=bbox)],
    )
    monkeypatch.setattr(
        "app.tasks.pipeline.get_settings",
        lambda: get_settings().model_copy(update={"app_data_dir": tmp_path}),
    )

    watch_root = tmp_path / "watch-root"
    batch_dir = watch_root / "BATCH-EVT"
    batch_dir.mkdir(parents=True)
    image_path = batch_dir / "board-1.jpg"
    Image.new("RGB", (64, 64), (0, 0, 0)).save(image_path, format="JPEG")

    generator = _event_stream(_NeverDisconnectedRequest())
    collector = asyncio.ensure_future(_collect_chunks(generator, count=3))
    await asyncio.sleep(0.3)
    try:
        summary = await ingestion_service.scan_directory(
            db_session, watch_root, source=ImageSource.DIRECTORY_SCAN
        )
        assert summary.ingested == 1
        image_id = summary.files[0].image_id
        assert image_id is not None

        await asyncio.to_thread(run_inference.apply, args=[str(image_id)])

        chunks = await asyncio.wait_for(collector, timeout=5)
    finally:
        await generator.aclose()

    events = [_parse_sse_chunk(c) for c in chunks]
    assert [e["event"] for e in events] == [
        "inspection.created",
        "detection.completed",
        "analysis.completed",
    ]
    assert all(e["data"]["id"] == str(image_id) for e in events)
    assert events[1]["data"]["status"] == "COMPLETED"
    assert "analysis_id" in events[2]["data"]
