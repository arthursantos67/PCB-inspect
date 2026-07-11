"""Runs the warm-started YOLO model against a single image and returns raw per-box
predictions — normalized bbox + confidence + class name. No thresholding or persistence
here; `app.inference.service` owns the RV-03 store/report threshold split.

`model` is typed as `Any` rather than `ultralytics.YOLO` deliberately — see the module
docstring in `app.inference.model` for why this package never imports `ultralytics` at
module scope.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RawDetection:
    defect_type: str  # raw class name as reported by the model (matches DefectType values)
    confidence: float
    bbox: dict[str, float]  # normalized {x1,y1,x2,y2}, clamped to [0,1]


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def detect(model: Any, image_path: Path, *, min_confidence: float) -> list[RawDetection]:
    """`min_confidence` is passed straight through as the model's own confidence floor
    (`min_confidence_store`, RV-03) so NMS doesn't do unnecessary work on candidates the
    system would discard anyway.
    """
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found at inference time: {image_path}")

    results = model.predict(source=str(image_path), conf=min_confidence, verbose=False)
    result = results[0]

    detections: list[RawDetection] = []
    if result.boxes is None:
        return detections

    names = result.names
    for box in result.boxes:
        cls_idx = int(box.cls.item())
        confidence = float(box.conf.item())
        x1, y1, x2, y2 = (_clamp(float(v)) for v in box.xyxyn[0].tolist())
        detections.append(
            RawDetection(
                defect_type=names[cls_idx],
                confidence=confidence,
                bbox={"x1": x1, "y1": y1, "x2": x2, "y2": y2},
            )
        )
    return detections
