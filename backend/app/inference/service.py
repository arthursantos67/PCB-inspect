"""Orchestrates a single image through the inference stage (FR-05): run YOLO, apply the two
confidence thresholds (RV-03), persist Detection rows with model version traceability
(RV-05), generate the annotated image for images with at least one reportable detection
(RV-04), and transition `InspectionImage` accordingly.

`DETECTED` is reached when there's at least one reportable detection (Issue 7 picks up from
there — baseline/agent analysis). Otherwise the image goes straight to `COMPLETED` with no
defect result (FR-05's no-defect path) even if lower-confidence detections were persisted
for audit purposes (RV-03's rationale) — reportability, not storage, decides the path.
"""

from decimal import Decimal
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.inference.annotate import write_annotated_image
from app.inference.detect import RawDetection, detect
from app.inference.model import LoadedModel
from app.inspections.state import transition
from app.models import Detection, InspectionImage
from app.models.enums import DefectType, ImageStatus
from app.settings.service import get_config_value
from app.tasks.errors import TransientProcessingError

DEFAULT_MIN_CONFIDENCE_STORE = 0.25
DEFAULT_MIN_CONFIDENCE_REPORT = 0.50


async def _get_thresholds(db: AsyncSession) -> tuple[float, float]:
    store = await get_config_value(db, "min_confidence_store", DEFAULT_MIN_CONFIDENCE_STORE)
    report = await get_config_value(db, "min_confidence_report", DEFAULT_MIN_CONFIDENCE_REPORT)
    return float(store), float(report)


def _to_confidence_decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 3)))


async def process_image(
    db: AsyncSession,
    image: InspectionImage,
    loaded: LoadedModel,
    *,
    app_data_dir: Path,
) -> None:
    min_store, min_report = await _get_thresholds(db)

    try:
        raw_detections = detect(loaded.model, Path(image.original_path), min_confidence=min_store)
    except FileNotFoundError as exc:
        raise TransientProcessingError(f"Image not readable at inference time: {exc}") from exc

    # Defensive re-filter: `detect()` already asks the model for `min_store` as its own
    # confidence floor, but that's an internal NMS parameter, not a contract — this is what
    # actually enforces RV-03 (confidence >= min_confidence_store persisted).
    stored: list[RawDetection] = [d for d in raw_detections if d.confidence >= min_store]
    reportable = [d for d in stored if d.confidence >= min_report]

    for raw in stored:
        db.add(
            Detection(
                image_id=image.id,
                defect_type=DefectType(raw.defect_type),
                bbox=raw.bbox,
                confidence=_to_confidence_decimal(raw.confidence),
                is_reported=raw.confidence >= min_report,
                model_version_id=loaded.model_version_id,
            )
        )

    if reportable:
        annotated_path = write_annotated_image(
            source_path=Path(image.original_path),
            detections=stored,
            app_data_dir=app_data_dir,
            image_id=image.id,
        )
        image.annotated_path = str(annotated_path)
        transition(image, ImageStatus.DETECTED)
    else:
        transition(image, ImageStatus.COMPLETED)
