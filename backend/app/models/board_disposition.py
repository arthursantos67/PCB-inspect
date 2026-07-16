import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import BoardDispositionDecision, pg_enum


class BoardDisposition(Base):
    """A board's final disposition (FR-10, section 10.2) — one row per `InspectionImage`
    (RN-09); a later change updates `decision` in place, with the previous value captured in
    the accompanying `AuditLog` entry rather than versioned here.
    """

    __tablename__ = "board_disposition"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inspection_image.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    decision: Mapped[BoardDispositionDecision] = mapped_column(
        pg_enum(BoardDispositionDecision, "board_disposition_decision"),
        nullable=False,
    )
    decided_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
