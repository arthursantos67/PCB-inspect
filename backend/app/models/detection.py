import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import DefectType, DetectionReview, DetectionSource, pg_enum

# RN-01 — confidence bounded to [0,1]; bbox normalized [0,1] with x1<x2, y1<y2.
_BBOX_CHECK = (
    "(bbox ? 'x1') AND (bbox ? 'y1') AND (bbox ? 'x2') AND (bbox ? 'y2') "
    "AND (bbox->>'x1')::numeric >= 0 AND (bbox->>'y1')::numeric >= 0 "
    "AND (bbox->>'x2')::numeric <= 1 AND (bbox->>'y2')::numeric <= 1 "
    "AND (bbox->>'x1')::numeric < (bbox->>'x2')::numeric "
    "AND (bbox->>'y1')::numeric < (bbox->>'y2')::numeric"
)


class Detection(Base):
    __tablename__ = "detection"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint(_BBOX_CHECK, name="bbox_normalized_and_ordered"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inspection_image.id", ondelete="CASCADE"), nullable=False
    )
    defect_type: Mapped[DefectType] = mapped_column(
        pg_enum(DefectType, "defect_type"),
        nullable=False,
    )
    bbox: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    is_reported: Mapped[bool] = mapped_column(nullable=False, default=False)
    # Nullable: a manually-drawn detection (source=MANUAL) has no producing model version.
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_version.id"), nullable=True
    )
    review: Mapped[DetectionReview] = mapped_column(
        pg_enum(DetectionReview, "detection_review"),
        nullable=False,
        default=DetectionReview.UNREVIEWED,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=True
    )
    source: Mapped[DetectionSource] = mapped_column(
        pg_enum(DetectionSource, "detection_source"),
        nullable=False,
        default=DetectionSource.MODEL,
    )
