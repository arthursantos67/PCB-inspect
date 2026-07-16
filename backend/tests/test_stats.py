"""GET /api/v1/stats/{summary,trends,by-defect-type} (FR-08, PRD section 11.2) — correct
aggregates, RN-07 (unreported detections excluded), the period selector (7d/30d/90d), and the
Redis cache's TTL behavior (section 3.6).

Detections/analyses are constructed directly against the ORM, same convention as
tests/test_inspections_list.py — this file only exercises the aggregation/caching logic
itself, not the full ingestion+inference pipeline.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Batch, Board, Detection, InspectionImage, ModelVersion
from app.models.enums import DefectType, ImageSource, ImageStatus
from app.stats.cache import invalidate_all

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


@pytest.fixture(autouse=True)
async def _clear_stats_cache() -> None:
    """The Redis cache (section 3.6) persists across tests since it isn't torn down by the
    `db_session` fixture's table TRUNCATE — without this, a cached value from an earlier test
    could leak into a later one that expects a cache miss.
    """
    await invalidate_all()
    yield
    await invalidate_all()


async def _make_model_version(db: AsyncSession) -> ModelVersion:
    model_version = ModelVersion(version="v1.0.0", weights_path="/weights/best.pt", is_active=True)
    db.add(model_version)
    await db.flush()
    return model_version


async def _make_board(db: AsyncSession, batch_number: str, board_number: str) -> Board:
    batch = await db.scalar(select(Batch).where(Batch.batch_number == batch_number))
    if batch is None:
        batch = Batch(batch_number=batch_number)
        db.add(batch)
        await db.flush()
    board = Board(batch_id=batch.id, board_number=board_number)
    db.add(board)
    await db.flush()
    return board


async def _make_image(
    db: AsyncSession,
    board: Board,
    *,
    status: ImageStatus,
    processed_at: datetime | None,
) -> InspectionImage:
    image = InspectionImage(
        board_id=board.id,
        source=ImageSource.WATCH_FOLDER,
        original_path=f"/tmp/{uuid.uuid4()}.jpg",
        checksum_sha256=uuid.uuid4().hex,
        status=status,
        processed_at=processed_at,
    )
    db.add(image)
    await db.flush()
    return image


async def _make_detection(
    db: AsyncSession,
    image: InspectionImage,
    model_version: ModelVersion,
    defect_type: DefectType,
    *,
    is_reported: bool = True,
) -> Detection:
    detection = Detection(
        image_id=image.id,
        defect_type=defect_type,
        bbox={"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4},
        confidence=Decimal("0.900") if is_reported else Decimal("0.300"),
        is_reported=is_reported,
        model_version_id=model_version.id,
    )
    db.add(detection)
    await db.flush()
    return detection


async def _get(client: AsyncClient, token: str, path: str, **params: object) -> dict:
    response = await client.get(path, params=params, headers=_auth_headers(token))
    assert response.status_code == 200, response.text
    return response.json()


# --- Auth ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["/api/v1/stats/summary", "/api/v1/stats/trends", "/api/v1/stats/by-defect-type"]
)
async def test_requires_authentication(client: AsyncClient, path: str) -> None:
    response = await client.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


# --- Summary: correct aggregates + RN-07 ----------------------------------------------------


async def test_summary_correct_aggregates_and_rn07(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    model_version = await _make_model_version(db_session)
    board = await _make_board(db_session, "BATCH-A", "A1")
    now = datetime.now(UTC)

    # Reported defect, processed within the last 24h -> counts toward total, defects, 24h.
    img1 = await _make_image(
        db_session, board, status=ImageStatus.COMPLETED, processed_at=now - timedelta(hours=1)
    )
    await _make_detection(db_session, img1, model_version, DefectType.MOUSE_BITE)

    # Reported defect, processed within the last 24h.
    img2 = await _make_image(
        db_session, board, status=ImageStatus.COMPLETED, processed_at=now - timedelta(hours=2)
    )
    await _make_detection(db_session, img2, model_version, DefectType.SHORT)

    # No detections at all, processed > 24h ago -> counts toward total/quality, not 24h.
    await _make_image(
        db_session, board, status=ImageStatus.COMPLETED, processed_at=now - timedelta(days=2)
    )

    # RN-07: an unreported (low-confidence) detection must NOT make this count as "with
    # defects" -> counts toward total/quality (as defect-free), not 24h.
    img4 = await _make_image(
        db_session, board, status=ImageStatus.COMPLETED, processed_at=now - timedelta(days=3)
    )
    await _make_detection(
        db_session, img4, model_version, DefectType.SPUR, is_reported=False
    )

    # Not COMPLETED -> excluded from every aggregate entirely.
    await _make_image(db_session, board, status=ImageStatus.QUEUED, processed_at=None)
    failed = await _make_image(
        db_session, board, status=ImageStatus.PROCESSING, processed_at=None
    )
    failed.status = ImageStatus.FAILED
    failed.processed_at = now

    await db_session.commit()

    body = await _get(client, token, "/api/v1/stats/summary")
    assert body["total_inspected"] == 4
    assert body["total_with_defects"] == 2
    assert body["quality_rate"] == 50.0
    assert body["last_24h_count"] == 2


async def test_summary_with_no_data_reports_zero(client: AsyncClient) -> None:
    token = await _setup_account(client)
    body = await _get(client, token, "/api/v1/stats/summary")
    assert body == {
        "total_inspected": 0,
        "total_with_defects": 0,
        "quality_rate": 0.0,
        "last_24h_count": 0,
        "analyses_validated": 0,
        "analyses_rejected": 0,
        "analysis_precision_rate": None,
    }


# --- Summary: precision metrics (FR-10) ------------------------------------------------------


async def test_summary_precision_rate_reflects_validated_vs_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    model_version = await _make_model_version(db_session)
    board = await _make_board(db_session, "BATCH-A", "A1")
    now = datetime.now(UTC)

    from app.analyses.service import create_baseline_analysis

    validated_img = await _make_image(
        db_session, board, status=ImageStatus.DETECTED, processed_at=now
    )
    validated_detection = await _make_detection(
        db_session, validated_img, model_version, DefectType.MOUSE_BITE
    )
    validated_analysis = await create_baseline_analysis(
        db_session, validated_img, [validated_detection]
    )

    rejected_img = await _make_image(
        db_session, board, status=ImageStatus.DETECTED, processed_at=now
    )
    rejected_detection = await _make_detection(
        db_session, rejected_img, model_version, DefectType.SHORT
    )
    rejected_analysis = await create_baseline_analysis(
        db_session, rejected_img, [rejected_detection]
    )

    pending_img = await _make_image(
        db_session, board, status=ImageStatus.DETECTED, processed_at=now
    )
    pending_detection = await _make_detection(
        db_session, pending_img, model_version, DefectType.SPUR
    )
    await create_baseline_analysis(db_session, pending_img, [pending_detection])

    await db_session.commit()

    validate_response = await client.post(
        f"/api/v1/analyses/{validated_analysis.id}/review",
        json={"action": "validated"},
        headers=_auth_headers(token),
    )
    assert validate_response.status_code == 200, validate_response.text

    reject_response = await client.post(
        f"/api/v1/analyses/{rejected_analysis.id}/review",
        json={"action": "rejected"},
        headers=_auth_headers(token),
    )
    assert reject_response.status_code == 200, reject_response.text

    body = await _get(client, token, "/api/v1/stats/summary")
    assert body["analyses_validated"] == 1
    assert body["analyses_rejected"] == 1
    assert body["analysis_precision_rate"] == 50.0


# --- By defect type: RN-07 + stable categories -----------------------------------------------


async def test_by_defect_type_excludes_unreported_and_includes_all_classes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    model_version = await _make_model_version(db_session)
    board = await _make_board(db_session, "BATCH-A", "A1")
    now = datetime.now(UTC)

    img1 = await _make_image(db_session, board, status=ImageStatus.COMPLETED, processed_at=now)
    await _make_detection(db_session, img1, model_version, DefectType.MOUSE_BITE)
    await _make_detection(db_session, img1, model_version, DefectType.MOUSE_BITE)
    await _make_detection(db_session, img1, model_version, DefectType.SHORT, is_reported=False)

    await db_session.commit()

    body = await _get(client, token, "/api/v1/stats/by-defect-type")
    assert body["total"] == 2
    counts = {row["defect_type"]: row["count"] for row in body["counts"]}
    assert counts == {
        "missing_hole": 0,
        "mouse_bite": 2,
        "open_circuit": 0,
        "short": 0,  # the unreported SHORT detection must not count (RN-07)
        "spur": 0,
        "spurious_copper": 0,
    }


# --- Trends: period selector -----------------------------------------------------------------


async def test_trends_period_selector_narrows_the_window(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    model_version = await _make_model_version(db_session)
    board = await _make_board(db_session, "BATCH-A", "A1")
    now = datetime.now(UTC)

    recent = await _make_image(
        db_session, board, status=ImageStatus.COMPLETED, processed_at=now - timedelta(days=1)
    )
    await _make_detection(db_session, recent, model_version, DefectType.MOUSE_BITE)

    mid_range = await _make_image(
        db_session, board, status=ImageStatus.COMPLETED, processed_at=now - timedelta(days=20)
    )
    await _make_detection(db_session, mid_range, model_version, DefectType.SHORT)

    outside_all = await _make_image(
        db_session, board, status=ImageStatus.COMPLETED, processed_at=now - timedelta(days=120)
    )
    await _make_detection(db_session, outside_all, model_version, DefectType.SPUR)

    await db_session.commit()

    def _total(points: list[dict]) -> int:
        return sum(point["total"] for point in points)

    body_7d = await _get(client, token, "/api/v1/stats/trends", period="7d")
    assert body_7d["period"] == "7d"
    assert _total(body_7d["points"]) == 1

    body_30d = await _get(client, token, "/api/v1/stats/trends", period="30d")
    assert _total(body_30d["points"]) == 2

    body_90d = await _get(client, token, "/api/v1/stats/trends", period="90d")
    assert _total(body_90d["points"]) == 2  # the 120-day-old point is still outside 90d


async def test_trends_zero_fills_buckets_with_no_data(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    model_version = await _make_model_version(db_session)
    board = await _make_board(db_session, "BATCH-A", "A1")
    now = datetime.now(UTC)

    img = await _make_image(
        db_session, board, status=ImageStatus.COMPLETED, processed_at=now - timedelta(days=1)
    )
    await _make_detection(db_session, img, model_version, DefectType.MOUSE_BITE)
    await db_session.commit()

    body = await _get(client, token, "/api/v1/stats/trends", period="7d", granularity="day")
    # A 7-day window has at least 7 daily buckets even though only one has data.
    assert len(body["points"]) >= 7
    assert sum(1 for point in body["points"] if point["total"] == 0) >= 5


# --- Cache behavior ----------------------------------------------------------------------------


async def test_cache_hit_within_ttl_then_recomputes_after_invalidation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    board = await _make_board(db_session, "BATCH-A", "A1")
    now = datetime.now(UTC)

    await _make_image(db_session, board, status=ImageStatus.COMPLETED, processed_at=now)
    await db_session.commit()

    first = await _get(client, token, "/api/v1/stats/summary")
    assert first["total_inspected"] == 1

    # A second COMPLETED image lands directly in the DB, bypassing the pipeline task that
    # would normally invalidate the cache (app.tasks.pipeline) -> the cached value must still
    # be served as long as the TTL hasn't lapsed.
    await _make_image(db_session, board, status=ImageStatus.COMPLETED, processed_at=now)
    await db_session.commit()

    cached_again = await _get(client, token, "/api/v1/stats/summary")
    assert cached_again["total_inspected"] == 1  # stale on purpose: proves the cache hit

    settings = get_settings()
    redis_client = Redis.from_url(settings.redis_url)
    try:
        assert await redis_client.exists("stats:summary:all:all")
    finally:
        await redis_client.aclose()

    await invalidate_all()

    recomputed = await _get(client, token, "/api/v1/stats/summary")
    assert recomputed["total_inspected"] == 2
