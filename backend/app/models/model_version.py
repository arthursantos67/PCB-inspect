import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ModelEvaluationStatus, pg_enum


class ModelVersion(Base):
    __tablename__ = "model_version"
    __table_args__ = (
        # RN-02 — at most one active model version.
        Index(
            "ix_model_version_single_active",
            "is_active",
            unique=True,
            postgresql_where="is_active = true",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version: Mapped[str] = mapped_column(unique=True, nullable=False)
    # Local filesystem path of the .pt file — no object-storage key.
    weights_path: Mapped[str] = mapped_column(nullable=False)
    # Only ever written by the golden-set evaluation task (RN-10) — never accepted directly
    # from the registration payload (FR-12's "Evaluation Is Real" acceptance criterion).
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    evaluation_status: Mapped[ModelEvaluationStatus] = mapped_column(
        pg_enum(ModelEvaluationStatus, "model_evaluation_status"),
        nullable=False,
        default=ModelEvaluationStatus.PENDING,
    )
    evaluation_error: Mapped[str | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
