import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import DatasetExportStatus, pg_enum


class DatasetExport(Base):
    """Feedback dataset export in YOLO format (FR-18, section 10.2) — generated asynchronously
    by `app.tasks.dataset_exports` and indexed here so it can be found and re-downloaded later,
    until retention (FR-17) purges it. This is the "data flywheel" output: retraining itself
    stays external to the software (section 17), this only prepares the labeled input.
    """

    __tablename__ = "dataset_export"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Period, defect types, review status (FR-18) — same shape as `DatasetExportFiltersIn`.
    filters: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[DatasetExportStatus] = mapped_column(
        pg_enum(DatasetExportStatus, "dataset_export_status"),
        nullable=False,
        default=DatasetExportStatus.PENDING,
    )
    # Statistics (by defect type/review status), filters applied, and source model version(s)
    # (RV-05 traceability) — populated once COMPLETED; also written as manifest.json in the ZIP.
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Local filesystem path under the configured `reports_output_dir` (FR-13) once COMPLETED.
    file_path: Mapped[str | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(nullable=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
