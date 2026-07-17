"""Query-parameter -> SQLAlchemy filter translation for dataset export (FR-18).

Deliberately its own filter builder rather than reusing `app.inspections.filters`: that module
decides which *images* match a search (image-level `exists()` checks), while a dataset export
must decide which *detections* actually get written into `labels/` — a `defect_type` filter here
excludes non-matching detections outright, it doesn't just gate whether an image is included.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, select

from app.models import Detection, InspectionImage
from app.models.enums import DefectType, DetectionReview

# Only reviewed detections carry export-worthy signal (FR-18): `unreviewed` is neither a
# confirmed label nor a false-positive correction. Manual annotations (FR-10) are already
# `review=confirmed` at creation time, so they fall out of this set with no special-casing.
_EXPORTABLE_REVIEWS = (DetectionReview.CONFIRMED, DetectionReview.FALSE_POSITIVE)


@dataclass
class DatasetExportFilters:
    defect_type: list[DefectType] | None = None
    review_status: list[DetectionReview] | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


def matching_detections_query(
    filters: DatasetExportFilters,
) -> Select[tuple[Detection, InspectionImage]]:
    """Every `(Detection, InspectionImage)` pair eligible for export under `filters`.

    RN-07: only detections that were actually surfaced to the operator (`is_reported`) can have
    been reviewed in the first place, so this is filtered the same way reports/dashboards are.
    """
    review_values = filters.review_status or list(_EXPORTABLE_REVIEWS)
    stmt = (
        select(Detection, InspectionImage)
        .join(InspectionImage, Detection.image_id == InspectionImage.id)
        .where(Detection.is_reported.is_(True))
        .where(Detection.review.in_(review_values))
    )
    if filters.defect_type:
        stmt = stmt.where(Detection.defect_type.in_(filters.defect_type))
    if filters.date_from:
        stmt = stmt.where(InspectionImage.created_at >= filters.date_from)
    if filters.date_to:
        stmt = stmt.where(InspectionImage.created_at <= filters.date_to)
    return stmt.order_by(InspectionImage.id.asc(), Detection.id.asc())
