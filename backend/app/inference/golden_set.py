"""Golden-set evaluation (FR-12, NFR-05): computes mAP@50/mAP@50-95/per-class metrics for a
candidate model version by running it — through the same `app.inference.detect` code path
production inference uses (`load_candidate_weights` + `detect`, both from `app.inference.*`)
— against a versioned local reference set of images and YOLO-format labels. Metrics are never
self-reported (RN-10): this module is the only place `ModelVersion.metrics` values come from.

Golden-set layout, rooted at `Settings.golden_set_dir` (alongside app-data, never the
read-only watch root — section 3.1/14.1):

    golden-set/
      manifest.json   {"version": ..., "classes": [...], "images": [{"image": ..., "label": ...}]}
      images/...
      labels/...      YOLO format: one "<class_idx> <cx> <cy> <w> <h>" line per box, normalized

`classes` lists the six `DefectType` values in the order the label files' `<class_idx>`
refers to. Ground truth and predictions are compared by class *name* (`RawDetection
.defect_type`, already a name per `app.inference.detect`), not raw index, so a candidate
model's own `model.names` ordering never has to match the golden set's.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import ApiError
from app.inference.detect import RawDetection, detect
from app.inference.model import load_candidate_weights

BBox = tuple[float, float, float, float]

# Full evaluation floor — predictions below production's own store threshold (RV-03) still
# matter here: mAP is computed over the model's full precision/recall curve, not the
# thresholded subset production actually persists.
_EVAL_MIN_CONFIDENCE = 0.001

# COCO-style mAP@50-95: ten IoU thresholds, 0.50 through 0.95 in steps of 0.05.
IOU_THRESHOLDS_50_95: tuple[float, ...] = tuple(round(0.5 + 0.05 * i, 2) for i in range(10))


@dataclass(frozen=True)
class GoldenSetImage:
    image_path: Path
    label_path: Path


@dataclass(frozen=True)
class GoldenSetManifest:
    version: str
    classes: list[str]
    images: list[GoldenSetImage]


@dataclass(frozen=True)
class GroundTruthBox:
    defect_type: str
    bbox: BBox


@dataclass(frozen=True)
class EvaluationMetrics:
    map50: float
    map50_95: float
    per_class: dict[str, float]
    golden_set_version: str
    image_count: int


def load_manifest(golden_set_dir: Path) -> GoldenSetManifest:
    manifest_path = golden_set_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ApiError(
            "GOLDEN_SET_NOT_CONFIGURED",
            f"No golden-set manifest found at {manifest_path}.",
            422,
        )
    try:
        raw = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise ApiError(
            "GOLDEN_SET_NOT_CONFIGURED", f"Golden-set manifest is unreadable: {exc}", 422
        ) from exc

    images = [
        GoldenSetImage(
            image_path=golden_set_dir / entry["image"],
            label_path=golden_set_dir / entry["label"],
        )
        for entry in raw.get("images", [])
    ]
    if not images:
        raise ApiError("GOLDEN_SET_EMPTY", "The golden-set manifest lists no images.", 422)

    return GoldenSetManifest(
        version=str(raw["version"]), classes=list(raw["classes"]), images=images
    )


def _yolo_to_xyxy(cx: float, cy: float, w: float, h: float) -> BBox:
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def load_ground_truth(label_path: Path, classes: list[str]) -> list[GroundTruthBox]:
    """Empty ground truth (missing label file, or an image with no defects) is valid — not
    every golden-set image needs a defect on it.
    """
    if not label_path.is_file():
        return []
    boxes: list[GroundTruthBox] = []
    for line in label_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        class_idx_raw, cx_raw, cy_raw, w_raw, h_raw = stripped.split()[:5]
        boxes.append(
            GroundTruthBox(
                defect_type=classes[int(class_idx_raw)],
                bbox=_yolo_to_xyxy(float(cx_raw), float(cy_raw), float(w_raw), float(h_raw)),
            )
        )
    return boxes


def _iou(a: BBox, b: BBox) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def _average_precision(scored: list[tuple[float, bool]], num_gt: int) -> float:
    """All-points (Pascal VOC 2010+) interpolated average precision: the monotonic
    (non-increasing, scanned right-to-left) precision envelope integrated over recall.
    """
    if num_gt == 0:
        return 0.0

    ordered = sorted(scored, key=lambda item: item[0], reverse=True)
    tp_cum = 0
    fp_cum = 0
    precisions: list[float] = []
    recalls: list[float] = []
    for _, is_tp in ordered:
        if is_tp:
            tp_cum += 1
        else:
            fp_cum += 1
        precisions.append(tp_cum / (tp_cum + fp_cum))
        recalls.append(tp_cum / num_gt)

    for i in range(len(precisions) - 2, -1, -1):
        precisions[i] = max(precisions[i], precisions[i + 1])

    ap = 0.0
    prev_recall = 0.0
    for precision, recall in zip(precisions, recalls, strict=True):
        ap += precision * (recall - prev_recall)
        prev_recall = recall
    return ap


def _class_ap_at_iou(
    predictions: list[tuple[str, float, BBox]],
    ground_truths: dict[str, list[BBox]],
    iou_threshold: float,
) -> float:
    num_gt = sum(len(boxes) for boxes in ground_truths.values())
    matched = {image_key: [False] * len(boxes) for image_key, boxes in ground_truths.items()}

    scored: list[tuple[float, bool]] = []
    for image_key, confidence, bbox in sorted(predictions, key=lambda p: p[1], reverse=True):
        candidates = ground_truths.get(image_key, [])
        best_iou = 0.0
        best_idx = -1
        for idx, gt_bbox in enumerate(candidates):
            if matched[image_key][idx]:
                continue
            iou = _iou(bbox, gt_bbox)
            if iou > best_iou:
                best_iou = iou
                best_idx = idx
        is_tp = best_idx != -1 and best_iou >= iou_threshold
        if is_tp:
            matched[image_key][best_idx] = True
        scored.append((confidence, is_tp))

    return _average_precision(scored, num_gt)


def compute_map(
    predictions_by_image: dict[str, list[RawDetection]],
    ground_truth_by_image: dict[str, list[GroundTruthBox]],
    classes: list[str],
) -> tuple[float, float, dict[str, float]]:
    """Pure metric computation, independent of how predictions/ground truth were produced —
    unit-testable without a model or the filesystem. Classes with no ground-truth box in the
    golden set are reported as 0.0 and excluded from the mAP average (their AP is undefined,
    standard COCO convention), never silently counted as a perfect score.
    """
    per_class_ap50: dict[str, float] = {}
    per_class_ap_range: dict[str, list[float]] = {}
    included_classes: list[str] = []

    for cls in classes:
        preds = [
            (image_key, detection.confidence, _bbox_tuple(detection.bbox))
            for image_key, detections in predictions_by_image.items()
            for detection in detections
            if detection.defect_type == cls
        ]
        gts = {
            image_key: [box.bbox for box in boxes if box.defect_type == cls]
            for image_key, boxes in ground_truth_by_image.items()
        }
        num_gt = sum(len(boxes) for boxes in gts.values())
        if num_gt == 0:
            per_class_ap50[cls] = 0.0
            continue

        included_classes.append(cls)
        aps = [_class_ap_at_iou(preds, gts, threshold) for threshold in IOU_THRESHOLDS_50_95]
        per_class_ap50[cls] = aps[0]  # IOU_THRESHOLDS_50_95[0] == 0.5
        per_class_ap_range[cls] = aps

    if not included_classes:
        raise ApiError(
            "GOLDEN_SET_EMPTY", "The golden set contains no ground-truth boxes.", 422
        )

    map50 = sum(per_class_ap50[cls] for cls in included_classes) / len(included_classes)
    map50_95 = sum(
        sum(per_class_ap_range[cls]) / len(per_class_ap_range[cls]) for cls in included_classes
    ) / len(included_classes)
    return map50, map50_95, per_class_ap50


def _bbox_tuple(bbox: dict[str, float]) -> BBox:
    return (bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"])


def evaluate_weights(weights_path: str, manifest: GoldenSetManifest) -> EvaluationMetrics:
    """Runs `weights_path` against every image in `manifest` through the real
    `app.inference.detect.detect()` path (never a separate/trusted-input metrics field,
    FR-12's "Evaluation Is Real" acceptance criterion) and computes mAP@50/mAP@50-95/per-class.
    """
    model, _device = load_candidate_weights(weights_path)

    predictions_by_image: dict[str, list[RawDetection]] = {}
    ground_truth_by_image: dict[str, list[GroundTruthBox]] = {}
    for image in manifest.images:
        key = str(image.image_path)
        predictions_by_image[key] = detect(
            model, image.image_path, min_confidence=_EVAL_MIN_CONFIDENCE
        )
        ground_truth_by_image[key] = load_ground_truth(image.label_path, manifest.classes)

    map50, map50_95, per_class = compute_map(
        predictions_by_image, ground_truth_by_image, manifest.classes
    )
    return EvaluationMetrics(
        map50=map50,
        map50_95=map50_95,
        per_class=per_class,
        golden_set_version=manifest.version,
        image_count=len(manifest.images),
    )
