import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ImageSource, ImageStatus, pg_enum


class InspectionImage(Base):
    __tablename__ = "inspection_image"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    board_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("board.id"), nullable=True
    )
    source: Mapped[ImageSource] = mapped_column(
        pg_enum(ImageSource, "image_source"),
        nullable=False,
    )
    # Absolute local filesystem path to the camera-captured file; never copied (section 3.5).
    original_path: Mapped[str] = mapped_column(nullable=False)
    # Local filesystem path to the generated annotated image (app-data directory).
    annotated_path: Mapped[str | None] = mapped_column(nullable=True)
    checksum_sha256: Mapped[str] = mapped_column(nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ImageStatus] = mapped_column(
        pg_enum(ImageStatus, "image_status"),
        nullable=False,
        default=ImageStatus.QUEUED,
    )
    failure_reason: Mapped[str | None] = mapped_column(nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
