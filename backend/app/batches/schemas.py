import uuid
from datetime import datetime

from pydantic import BaseModel

from app.batches.service import BatchAggregate
from app.models.enums import DefectType, ImageStatus, Severity


class DefectTypeCount(BaseModel):
    defect_type: DefectType
    count: int


class BatchListItem(BaseModel):
    """One row of the batch-first inspections list."""

    batch_id: uuid.UUID
    batch_number: str
    board_count: int
    completed_count: int
    boards_with_defects: int
    defect_count: int
    defect_rate: float
    defect_types: list[DefectTypeCount]
    severity: Severity | None
    status: ImageStatus
    created_at: datetime
    last_activity_at: datetime

    @classmethod
    def from_aggregate(cls, aggregate: BatchAggregate) -> "BatchListItem":
        return cls(
            batch_id=aggregate.batch_id,
            batch_number=aggregate.batch_number,
            board_count=aggregate.board_count,
            completed_count=aggregate.completed_count,
            boards_with_defects=aggregate.boards_with_defects,
            defect_count=aggregate.defect_count,
            defect_rate=aggregate.defect_rate,
            defect_types=[
                DefectTypeCount(defect_type=defect_type, count=count)
                for defect_type, count in sorted(
                    aggregate.defect_counts.items(), key=lambda item: -item[1]
                )
            ],
            severity=aggregate.severity,
            status=aggregate.status,
            created_at=aggregate.created_at,
            last_activity_at=aggregate.last_activity_at,
        )


class PaginatedBatches(BaseModel):
    count: int
    results: list[BatchListItem]
