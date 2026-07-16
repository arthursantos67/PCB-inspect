"""Response shapes for `GET /api/v1/stats/{summary,trends,by-defect-type}` (FR-08, PRD
section 11.2) — dashboard aggregates (FE-02). Every count here is derived exclusively from
`COMPLETED` images and `is_reported=true` detections (RN-07).
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.models.enums import DefectType

Period = Literal["7d", "30d", "90d"]
Granularity = Literal["day", "week", "month"]


class StatsSummary(BaseModel):
    """Backs the dashboard `StatCard` row (FE-02). `analysis_precision_rate` is FR-10's
    "system precision metrics": the share of *reviewed* analyses (validated or rejected,
    `Analysis.review_status != PENDING`) that were validated — `None` until at least one
    review exists, so the dashboard can distinguish "no feedback yet" from "0% validated".
    """

    total_inspected: int
    total_with_defects: int
    quality_rate: float
    last_24h_count: int
    analyses_validated: int
    analyses_rejected: int
    analysis_precision_rate: float | None


class DefectTypeCount(BaseModel):
    defect_type: DefectType
    count: int


class StatsByDefectType(BaseModel):
    """All 6 classes are always present (even at `count=0`) so the distribution bar chart
    (FE-02) has a stable set of categories across requests.
    """

    total: int
    counts: list[DefectTypeCount]


class TrendPoint(BaseModel):
    bucket: date
    total: int
    by_defect_type: dict[DefectType, int]


class StatsTrends(BaseModel):
    """Backs `DefectTrendChart` (FE-02) — `points` covers every bucket in `period`,
    zero-filled where no reported defect occurred, so the chart's x-axis is continuous.
    """

    period: Period
    granularity: Granularity
    points: list[TrendPoint]
