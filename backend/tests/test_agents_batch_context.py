"""`app.agents.batch_context.load_batch_context` — the per-batch defect frequency the agent
prompts reason from.
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.batch_context import load_batch_context
from app.models import Batch, Board, Detection, InspectionImage, ModelVersion
from app.models.enums import DefectType, ImageSource, ImageStatus


async def _make_model_version(db: AsyncSession) -> ModelVersion:
    model_version = ModelVersion(version="v1.0.0", weights_path="/weights/best.pt", is_active=True)
    db.add(model_version)
    await db.flush()
    return model_version


async def _make_image(
    db: AsyncSession, board: Board | None, *, status: ImageStatus = ImageStatus.COMPLETED
) -> InspectionImage:
    image = InspectionImage(
        board_id=board.id if board is not None else None,
        source=ImageSource.WATCH_FOLDER,
        original_path=f"/tmp/{uuid.uuid4()}.jpg",
        checksum_sha256=uuid.uuid4().hex,
        status=status,
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
) -> None:
    db.add(
        Detection(
            image_id=image.id,
            defect_type=defect_type,
            bbox={"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4},
            confidence=Decimal("0.900") if is_reported else Decimal("0.300"),
            is_reported=is_reported,
            model_version_id=model_version.id,
        )
    )
    await db.flush()


async def test_counts_every_reported_detection_in_the_board_s_batch(
    db_session: AsyncSession,
) -> None:
    model_version = await _make_model_version(db_session)
    batch = Batch(batch_number="BATCH-A")
    db_session.add(batch)
    await db_session.flush()
    board_a = Board(batch_id=batch.id, board_number="B1")
    board_b = Board(batch_id=batch.id, board_number="B2")
    board_c = Board(batch_id=batch.id, board_number="B3")
    db_session.add_all([board_a, board_b, board_c])
    await db_session.flush()
    image_a = await _make_image(db_session, board_a)
    image_b = await _make_image(db_session, board_b)
    await _make_image(db_session, board_c)
    await _make_detection(db_session, image_a, model_version, DefectType.SHORT)
    await _make_detection(db_session, image_a, model_version, DefectType.SHORT)
    await _make_detection(db_session, image_b, model_version, DefectType.SHORT)
    await _make_detection(db_session, image_b, model_version, DefectType.SPUR)

    context = await load_batch_context(db_session, image_a)

    assert context is not None
    assert context.batch_number == "BATCH-A"
    assert context.boards_inspected == 3
    assert context.boards_with_defects == 2
    assert context.frequency(DefectType.SHORT).occurrences == 3
    assert context.frequency(DefectType.SHORT).boards_affected == 2
    assert context.frequency(DefectType.SPUR).occurrences == 1


async def test_unseen_defect_class_reports_zero_rather_than_missing(
    db_session: AsyncSession,
) -> None:
    model_version = await _make_model_version(db_session)
    batch = Batch(batch_number="BATCH-A")
    db_session.add(batch)
    await db_session.flush()
    board = Board(batch_id=batch.id, board_number="B1")
    db_session.add(board)
    await db_session.flush()
    image = await _make_image(db_session, board)
    await _make_detection(db_session, image, model_version, DefectType.SHORT)

    context = await load_batch_context(db_session, image)

    assert context is not None
    assert context.frequency(DefectType.MISSING_HOLE).occurrences == 0
    assert context.frequency(DefectType.MISSING_HOLE).boards_affected == 0


async def test_unreported_detections_are_excluded(db_session: AsyncSession) -> None:
    """RN-07 again: a below-threshold detection must not make a defect look recurring."""
    model_version = await _make_model_version(db_session)
    batch = Batch(batch_number="BATCH-A")
    db_session.add(batch)
    await db_session.flush()
    board = Board(batch_id=batch.id, board_number="B1")
    db_session.add(board)
    await db_session.flush()
    image = await _make_image(db_session, board)
    await _make_detection(db_session, image, model_version, DefectType.SHORT, is_reported=False)

    context = await load_batch_context(db_session, image)

    assert context is not None
    assert context.boards_with_defects == 0
    assert context.frequency(DefectType.SHORT).occurrences == 0


async def test_boards_still_in_the_pipeline_are_not_counted_yet(db_session: AsyncSession) -> None:
    """The counts have to agree with the dashboard, the batch list and the reports, which all
    only count `COMPLETED` images (RN-07). A board still being processed elsewhere in the batch
    would otherwise let the AI text cite numbers the screen next to it contradicts.

    The board being analysed right now is the one exception: it is `ANALYZING` at this point in
    the pipeline, and the prompt states these figures include it.
    """
    model_version = await _make_model_version(db_session)
    batch = Batch(batch_number="BATCH-A")
    db_session.add(batch)
    await db_session.flush()
    analysed_board = Board(batch_id=batch.id, board_number="B1")
    finished_board = Board(batch_id=batch.id, board_number="B2")
    in_flight_board = Board(batch_id=batch.id, board_number="B3")
    db_session.add_all([analysed_board, finished_board, in_flight_board])
    await db_session.flush()
    analysed = await _make_image(db_session, analysed_board, status=ImageStatus.ANALYZING)
    finished = await _make_image(db_session, finished_board, status=ImageStatus.COMPLETED)
    in_flight = await _make_image(db_session, in_flight_board, status=ImageStatus.PROCESSING)
    await _make_detection(db_session, analysed, model_version, DefectType.SHORT)
    await _make_detection(db_session, finished, model_version, DefectType.SHORT)
    await _make_detection(db_session, in_flight, model_version, DefectType.SHORT)

    context = await load_batch_context(db_session, analysed)

    assert context is not None
    assert context.boards_inspected == 2
    assert context.boards_with_defects == 2
    assert context.frequency(DefectType.SHORT).occurrences == 2
    assert context.frequency(DefectType.SHORT).boards_affected == 2


async def test_image_without_a_board_has_no_batch_context(db_session: AsyncSession) -> None:
    image = await _make_image(db_session, None)

    assert await load_batch_context(db_session, image) is None


async def test_board_without_a_batch_has_no_batch_context(db_session: AsyncSession) -> None:
    board = Board(batch_id=None, board_number="B1")
    db_session.add(board)
    await db_session.flush()
    image = await _make_image(db_session, board)

    assert await load_batch_context(db_session, image) is None
