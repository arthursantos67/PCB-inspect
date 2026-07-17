import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ReportFormat, ReportStatus, ReportType, pg_enum


class Report(Base):
    """On-demand report generation (FR-11, section 10.2) — generated asynchronously by
    `app.tasks.reports` and indexed here so it can be found and re-downloaded later
    (FE-07's "findable later" acceptance criterion), until retention (FR-17) purges it.
    """

    __tablename__ = "report"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[ReportType] = mapped_column(pg_enum(ReportType, "report_type"), nullable=False)
    format: Mapped[ReportFormat] = mapped_column(
        pg_enum(ReportFormat, "report_format"), nullable=False
    )
    # Criteria used to generate the report: {inspection_id} for `individual`, the same filter
    # shape as GET /api/v1/inspections for `consolidated`, {date_from, date_to} for `executive`.
    filters: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[ReportStatus] = mapped_column(
        pg_enum(ReportStatus, "report_status"), nullable=False, default=ReportStatus.PENDING
    )
    # Local filesystem path under the configured `reports_output_dir` (FR-13) once COMPLETED.
    file_path: Mapped[str | None] = mapped_column(nullable=True)
    # Row count of the underlying data (consolidated report line items) — lets a test assert
    # this matches GET /api/v1/inspections' paginated `count` for the same filters (Issue 35).
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(nullable=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
