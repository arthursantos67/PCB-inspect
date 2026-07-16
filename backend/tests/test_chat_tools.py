"""Chat agent tool executors (PRD 5.4, issue #32) — each tool queries the database directly;
these tests exercise that query logic against ORM fixtures, independent of the LLM/tool-calling
loop (covered in tests/test_chat_agent.py).
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.tools import (
    execute_tool,
    get_analysis,
    get_defect_knowledge,
    get_defect_stats,
    search_analyses,
)
from app.models import Analysis, Batch, Board, Detection, InspectionImage, ModelVersion
from app.models.enums import (
    AnalysisSource,
    AnalysisStatus,
    DefectType,
    ImageSource,
    ImageStatus,
    Severity,
)

_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


async def _make_model_version(db: AsyncSession) -> ModelVersion:
    model_version = ModelVersion(version="v1.0.0", weights_path="/weights/best.pt", is_active=True)
    db.add(model_version)
    await db.flush()
    return model_version


async def _make_board(db: AsyncSession, batch_number: str, board_number: str) -> Board:
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
    created_at: datetime,
    status: ImageStatus = ImageStatus.COMPLETED,
) -> InspectionImage:
    image = InspectionImage(
        board_id=board.id,
        source=ImageSource.WATCH_FOLDER,
        original_path=f"/tmp/{uuid.uuid4()}.jpg",
        checksum_sha256=uuid.uuid4().hex,
        status=status,
        created_at=created_at,
    )
    db.add(image)
    await db.flush()
    return image


async def _make_detection(
    db: AsyncSession, image: InspectionImage, model_version: ModelVersion, defect_type: DefectType
) -> Detection:
    detection = Detection(
        image_id=image.id,
        defect_type=defect_type,
        bbox={"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4},
        confidence=Decimal("0.900"),
        is_reported=True,
        model_version_id=model_version.id,
    )
    db.add(detection)
    await db.flush()
    return detection


async def _make_analysis(
    db: AsyncSession, image: InspectionImage, *, severity: Severity, summary: str = "summary"
) -> Analysis:
    analysis = Analysis(
        image_id=image.id,
        status=AnalysisStatus.COMPLETED,
        source=AnalysisSource.KNOWLEDGE_BASE,
        severity_max=severity,
        executive_summary=summary,
    )
    db.add(analysis)
    await db.flush()
    return analysis


async def test_search_analyses_filters_by_batch(db_session: AsyncSession) -> None:
    model_version = await _make_model_version(db_session)
    board_a = await _make_board(db_session, "BATCH-A", "A1")
    board_b = await _make_board(db_session, "BATCH-B", "B1")
    img_a = await _make_image(db_session, board_a, created_at=_NOW)
    await _make_detection(db_session, img_a, model_version, DefectType.SHORT)
    img_b = await _make_image(db_session, board_b, created_at=_NOW)
    await _make_detection(db_session, img_b, model_version, DefectType.SPUR)
    await db_session.commit()

    result = await search_analyses(db_session, {"batch_number": "BATCH-A"})

    assert result["count"] == 1
    assert result["results"][0]["batch_number"] == "BATCH-A"


async def test_search_analyses_filters_by_defect_type(db_session: AsyncSession) -> None:
    model_version = await _make_model_version(db_session)
    board = await _make_board(db_session, "BATCH-A", "A1")
    img1 = await _make_image(db_session, board, created_at=_NOW)
    await _make_detection(db_session, img1, model_version, DefectType.SHORT)
    img2 = await _make_image(db_session, board, created_at=_NOW)
    await _make_detection(db_session, img2, model_version, DefectType.SPUR)
    await db_session.commit()

    result = await search_analyses(db_session, {"defect_type": "short"})

    assert result["count"] == 1
    assert result["results"][0]["inspection_id"] == str(img1.id)


async def test_search_analyses_respects_limit(db_session: AsyncSession) -> None:
    model_version = await _make_model_version(db_session)
    board = await _make_board(db_session, "BATCH-A", "A1")
    for _ in range(3):
        img = await _make_image(db_session, board, created_at=_NOW)
        await _make_detection(db_session, img, model_version, DefectType.SHORT)
    await db_session.commit()

    result = await search_analyses(db_session, {"limit": 2})

    assert result["count"] == 2


async def test_get_analysis_returns_full_detail(db_session: AsyncSession) -> None:
    model_version = await _make_model_version(db_session)
    board = await _make_board(db_session, "BATCH-A", "A1")
    image = await _make_image(db_session, board, created_at=_NOW)
    await _make_detection(db_session, image, model_version, DefectType.SHORT)
    await _make_analysis(
        db_session, image, severity=Severity.CRITICAL, summary="short circuit found"
    )
    await db_session.commit()

    result = await get_analysis(db_session, {"inspection_id": str(image.id)})

    assert result["batch_number"] == "BATCH-A"
    assert result["board_number"] == "A1"
    assert result["detections"] == [{"defect_type": "short", "confidence": 0.9}]
    assert result["analysis"]["executive_summary"] == "short circuit found"
    assert result["analysis"]["severity_max"] == "critical"


async def test_get_analysis_unknown_id_returns_error_payload_not_exception(
    db_session: AsyncSession,
) -> None:
    result = await get_analysis(db_session, {"inspection_id": str(uuid.uuid4())})
    assert "error" in result


async def test_get_analysis_malformed_id_returns_error_payload(db_session: AsyncSession) -> None:
    result = await get_analysis(db_session, {"inspection_id": "not-a-uuid"})
    assert "error" in result


async def test_get_defect_stats_by_defect_type(db_session: AsyncSession) -> None:
    model_version = await _make_model_version(db_session)
    board = await _make_board(db_session, "BATCH-A", "A1")
    img1 = await _make_image(db_session, board, created_at=_NOW)
    await _make_detection(db_session, img1, model_version, DefectType.SHORT)
    await _make_detection(db_session, img1, model_version, DefectType.SHORT)
    img2 = await _make_image(db_session, board, created_at=_NOW)
    await _make_detection(db_session, img2, model_version, DefectType.SPUR)
    await db_session.commit()

    result = await get_defect_stats(db_session, {"group_by": "defect_type"})

    counts = {row["defect_type"]: row["defect_count"] for row in result["results"]}
    assert counts["short"] == 2
    assert counts["spur"] == 1


async def test_get_defect_stats_by_batch_ranks_top_batches(db_session: AsyncSession) -> None:
    model_version = await _make_model_version(db_session)
    board_a = await _make_board(db_session, "BATCH-A", "A1")
    board_b = await _make_board(db_session, "BATCH-B", "B1")

    img_a = await _make_image(db_session, board_a, created_at=_NOW)
    await _make_detection(db_session, img_a, model_version, DefectType.SHORT)
    await _make_detection(db_session, img_a, model_version, DefectType.SPUR)

    img_b = await _make_image(db_session, board_b, created_at=_NOW)
    await _make_detection(db_session, img_b, model_version, DefectType.SHORT)
    await db_session.commit()

    result = await get_defect_stats(db_session, {"group_by": "batch", "limit": 5})

    assert result["results"][0] == {"batch_number": "BATCH-A", "defect_count": 2}
    assert result["results"][1] == {"batch_number": "BATCH-B", "defect_count": 1}


async def test_get_defect_stats_excludes_unreported_detections(db_session: AsyncSession) -> None:
    model_version = await _make_model_version(db_session)
    board = await _make_board(db_session, "BATCH-A", "A1")
    image = await _make_image(db_session, board, created_at=_NOW)
    detection = await _make_detection(db_session, image, model_version, DefectType.SHORT)
    detection.is_reported = False
    await db_session.commit()

    result = await get_defect_stats(db_session, {"group_by": "defect_type"})

    counts = {row["defect_type"]: row["defect_count"] for row in result["results"]}
    assert counts.get("short", 0) == 0


async def test_get_defect_stats_respects_date_range(db_session: AsyncSession) -> None:
    model_version = await _make_model_version(db_session)
    board = await _make_board(db_session, "BATCH-A", "A1")
    old_image = await _make_image(db_session, board, created_at=_NOW - timedelta(days=30))
    await _make_detection(db_session, old_image, model_version, DefectType.SHORT)
    recent_image = await _make_image(db_session, board, created_at=_NOW)
    await _make_detection(db_session, recent_image, model_version, DefectType.SHORT)
    await db_session.commit()

    result = await get_defect_stats(
        db_session, {"group_by": "defect_type", "date_from": (_NOW - timedelta(days=1)).isoformat()}
    )

    counts = {row["defect_type"]: row["defect_count"] for row in result["results"]}
    assert counts["short"] == 1


async def test_get_defect_knowledge_returns_static_reference(db_session: AsyncSession) -> None:
    result = await get_defect_knowledge(db_session, {"defect_type": "open_circuit"})

    assert result["defect_type"] == "open_circuit"
    assert result["default_severity"] == "critical"
    assert result["probable_causes"]


async def test_get_defect_knowledge_unknown_type_returns_error_payload(
    db_session: AsyncSession,
) -> None:
    result = await get_defect_knowledge(db_session, {"defect_type": "not_a_real_defect"})
    assert "error" in result


async def test_execute_tool_dispatches_by_name(db_session: AsyncSession) -> None:
    result = await execute_tool(db_session, "get_defect_knowledge", {"defect_type": "spur"})
    assert result["defect_type"] == "spur"
