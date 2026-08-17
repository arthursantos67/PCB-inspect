import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import (
    AnalysisReviewStatus,
    AnalysisSource,
    AnalysisStatus,
    DispositionRecommendation,
    Severity,
    pg_enum,
)


class Analysis(Base):
    """1:1 with InspectionImage (RN-03) — enforced via the unique constraint on image_id."""

    __tablename__ = "analysis"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inspection_image.id"), unique=True, nullable=False
    )
    status: Mapped[AnalysisStatus] = mapped_column(
        pg_enum(AnalysisStatus, "analysis_status"),
        nullable=False,
        default=AnalysisStatus.PENDING,
    )
    source: Mapped[AnalysisSource] = mapped_column(
        pg_enum(AnalysisSource, "analysis_source"),
        nullable=False,
    )
    # List of {description, causes, solutions, severity} per detection (FR-06).
    per_defect: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    executive_summary: Mapped[str | None] = mapped_column(nullable=True)
    disposition_recommendation: Mapped[DispositionRecommendation | None] = mapped_column(
        pg_enum(DispositionRecommendation, "disposition_recommendation"),
        nullable=True,
    )
    severity_max: Mapped[Severity | None] = mapped_column(
        pg_enum(Severity, "severity"),
        nullable=True,
    )
    llm_provider: Mapped[str | None] = mapped_column(nullable=True)
    llm_model: Mapped[str | None] = mapped_column(nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_status: Mapped[AnalysisReviewStatus] = mapped_column(
        pg_enum(AnalysisReviewStatus, "analysis_review_status"),
        nullable=False,
        default=AnalysisReviewStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Language `per_defect`/`executive_summary` above are written in (issue #50) — the station
    # language at the moment the analysis ran, which is not necessarily the station language
    # now. Nullable, and read as English when absent: every analysis written before the setting
    # existed was written in English. Stored as a plain string rather than a Postgres enum
    # because it is a rendering detail, and adding a supported language should not need a
    # `CREATE TYPE` migration on a running station.
    language: Mapped[str | None] = mapped_column(nullable=True)
    # Cache of this analysis' prose in the *other* languages, keyed by language code:
    # `{"pt": {"per_defect": [...], "executive_summary": "..."}}`. Filled on demand the first
    # time a report or a screen asks for a language the analysis was not written in
    # (`app.analyses.localization`), so the LLM is paid for once per analysis per language
    # instead of once per report. Never authoritative: `language` above says which text is the
    # original, and re-running the chain replaces the analysis and clears this.
    translations: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
