import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import AnalysisReviewAction, pg_enum


class AnalysisReview(Base):
    """Immutable history of validate/reject actions on an `Analysis` (FR-10, section 10.2) —
    queryable later independent of `Analysis.review_status`, which only reflects the latest
    action.
    """

    __tablename__ = "analysis_review"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=False
    )
    action: Mapped[AnalysisReviewAction] = mapped_column(
        pg_enum(AnalysisReviewAction, "analysis_review_action"),
        nullable=False,
    )
    comment: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
