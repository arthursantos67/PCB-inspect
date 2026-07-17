import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import QualityAlertType, pg_enum


class QualityAlert(Base):
    """A defect-rate threshold crossing (FR-19, section 10.2) — persisted by
    `app.tasks.alert_monitor.evaluate_thresholds` and surfaced as a dashboard banner (FE-02)
    until acknowledged (audited, FR-16). `acknowledged_by IS NULL` is what "active" means; there
    is no separate status column (this alert only ever has two states, unlike `Report`/
    `DatasetExport`'s multi-stage async generation).

    `context` carries the scope/observed-rate/threshold triple the PRD's ERD describes (batch
    number or window size, the rate that tripped it, the configured threshold) — same
    "substructure lives in JSONB" pattern as `ModelVersion.metrics` or `Report.filters`.
    """

    __tablename__ = "quality_alert"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[QualityAlertType] = mapped_column(
        pg_enum(QualityAlertType, "quality_alert_type"), nullable=False
    )
    # Groups alerts for the same batch/window across polls so the monitoring task can find
    # "the current alert for this scope" without parsing `context` — the batch's UUID (as a
    # string) for `defect_rate_batch`, or the fixed marker "global" for `defect_rate_window`
    # (that scope isn't tied to any one batch).
    scope_key: Mapped[str] = mapped_column(nullable=False)
    # {"batch_id": ..., "batch_number": ..., "observed_rate": ..., "threshold": ...} for a
    # batch alert; {"window_minutes": ..., "observed_rate": ..., "threshold": ...} for a window
    # alert.
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Re-arm bookkeeping (acceptance criterion "No Alert Storm"): set once the monitoring task
    # observes this scope back under threshold after an acknowledged alert — only then is a new
    # alert for the same scope allowed to fire, so a condition that's acknowledged but still
    # over threshold doesn't refire every poll cycle.
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
