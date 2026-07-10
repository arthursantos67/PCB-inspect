import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, func
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    """A local operator account — no role field, every account has identical access (PRD 2.2)."""

    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(nullable=False)
    full_name: Mapped[str] = mapped_column(nullable=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Removal is a soft delete (FR-02): other tables FK to user.id without ON DELETE SET
    # NULL/CASCADE, so a hard delete would break the historical records the PRD requires preserving.
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
