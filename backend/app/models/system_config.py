import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SystemConfig(Base):
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(primary_key=True)
    # Scalar or object — e.g. a float threshold, a string provider name, or a nested policy.
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    # Encrypted values (e.g. cloud LLM API keys) — the API returns only status, never the value.
    is_secret: Mapped[bool] = mapped_column(nullable=False, default=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
