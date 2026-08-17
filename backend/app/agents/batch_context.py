"""How often each defect type has already been seen in the board's own batch, fed to the
Analyst and the Summarizer as prompt context.

Without this, every board is analysed in isolation and the chain has no way to tell a one-off
from a pattern, which is what made its output read the same for every board with the same
defect class. With it, the same defect can be reasoned about differently: seen once in the
batch it is plausibly a local accident, seen on most boards of the batch it points at
something shared (a stencil, a paste deposit, a program). The counts are facts here, the
inference stays the model's job, and the prompt is explicit that frequency is evidence rather
than proof so simpler explanations are not ruled out.

Counts are a snapshot taken when this board's agent analysis runs: boards inspected later in
the same batch are not in them yet, and only `is_reported` detections on `COMPLETED` images are
counted, matching RN-07 and every other aggregate in the app (`app.batches.service`,
`app.reports.dataset`) — a board still mid-pipeline must not be counted here and left out of
the dashboard and the report next to it, or the AI text ends up citing numbers the screen
contradicts.
"""

from dataclasses import dataclass

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Batch, Board, Detection, InspectionImage
from app.models.enums import DefectType, ImageStatus


@dataclass(frozen=True)
class DefectFrequency:
    """One defect class's footprint in the batch so far."""

    occurrences: int
    boards_affected: int


@dataclass(frozen=True)
class BatchContext:
    batch_number: str
    boards_inspected: int
    boards_with_defects: int
    frequencies: dict[DefectType, DefectFrequency]

    def frequency(self, defect_type: DefectType) -> DefectFrequency:
        return self.frequencies.get(defect_type, DefectFrequency(occurrences=0, boards_affected=0))


async def load_batch_context(db: AsyncSession, image: InspectionImage) -> BatchContext | None:
    """`None` when the image has no linked board or that board has no batch (an ad hoc import
    that was never matched, FR-03) — there is no batch to compare against, so the prompts fall
    back to their per-board-only wording.
    """
    if image.board_id is None:
        return None
    row = (
        await db.execute(
            select(Board.batch_id, Batch.batch_number)
            .select_from(Board)
            .join(Batch, Board.batch_id == Batch.id)
            .where(Board.id == image.board_id)
        )
    ).first()
    if row is None:
        return None
    batch_id, batch_number = row

    # Which images count: the ones already finished, plus the board being analysed right now —
    # it is still `ANALYZING` at this point (`app.tasks.pipeline`), and the prompt states these
    # figures include it. Every other board still mid-pipeline is left out, which is what the
    # dashboard, the batch list and the reports do.
    counted_image = or_(
        InspectionImage.status == ImageStatus.COMPLETED, InspectionImage.id == image.id
    )

    boards_inspected = await db.scalar(
        select(func.count(distinct(Board.id)))
        .select_from(Board)
        .join(InspectionImage, InspectionImage.board_id == Board.id)
        .where(Board.batch_id == batch_id, counted_image)
    )
    boards_with_defects = await db.scalar(
        select(func.count(distinct(Board.id)))
        .select_from(Board)
        .join(InspectionImage, InspectionImage.board_id == Board.id)
        .join(Detection, Detection.image_id == InspectionImage.id)
        .where(Board.batch_id == batch_id, counted_image, Detection.is_reported.is_(True))
    )
    rows = (
        await db.execute(
            select(
                Detection.defect_type,
                func.count(Detection.id),
                func.count(distinct(Board.id)),
            )
            .select_from(Detection)
            .join(InspectionImage, Detection.image_id == InspectionImage.id)
            .join(Board, InspectionImage.board_id == Board.id)
            .where(Board.batch_id == batch_id, counted_image, Detection.is_reported.is_(True))
            .group_by(Detection.defect_type)
        )
    ).all()

    return BatchContext(
        batch_number=batch_number,
        boards_inspected=int(boards_inspected or 0),
        boards_with_defects=int(boards_with_defects or 0),
        frequencies={
            defect_type: DefectFrequency(occurrences=int(count), boards_affected=int(boards))
            for defect_type, count, boards in rows
        },
    )
