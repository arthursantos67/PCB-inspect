"""Golden-set evaluation math and manifest loading (FR-12, NFR-05).

`compute_map`/`load_manifest`/`load_ground_truth` are pure and tested directly here; the
"Evaluation Is Real" acceptance criterion (metrics only ever come from actually running
inference through `app.inference.detect.detect()`) is proven end to end by
`test_evaluate_weights_runs_real_detect_against_golden_set` below, using the same
`inference_backend == "fake"` deterministic stand-in `test_inference.py` uses (no
`weights/best.pt`, no GPU on CI runners).
"""

import json
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import get_settings
from app.core.errors import ApiError
from app.inference.detect import RawDetection
from app.inference.golden_set import (
    GroundTruthBox,
    compute_map,
    evaluate_weights,
    load_ground_truth,
    load_manifest,
)
from app.models.enums import DefectType

CLASSES = [d.value for d in DefectType]


def _bbox(x1: float, y1: float, x2: float, y2: float) -> dict[str, float]:
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}


# --- compute_map (pure) -----------------------------------------------------------------


def test_compute_map_perfect_prediction_scores_one() -> None:
    gt = {"img1": [GroundTruthBox(defect_type="short", bbox=(0.3, 0.3, 0.7, 0.7))]}
    preds = {
        "img1": [RawDetection(defect_type="short", confidence=0.9, bbox=_bbox(0.3, 0.3, 0.7, 0.7))]
    }

    map50, map50_95, per_class = compute_map(preds, gt, CLASSES)

    assert map50 == pytest.approx(1.0)
    assert map50_95 == pytest.approx(1.0)
    assert per_class["short"] == pytest.approx(1.0)


def test_compute_map_no_predictions_scores_zero() -> None:
    gt = {"img1": [GroundTruthBox(defect_type="short", bbox=(0.3, 0.3, 0.7, 0.7))]}
    preds: dict[str, list[RawDetection]] = {"img1": []}

    map50, map50_95, per_class = compute_map(preds, gt, CLASSES)

    assert map50 == pytest.approx(0.0)
    assert map50_95 == pytest.approx(0.0)
    assert per_class["short"] == pytest.approx(0.0)


def test_compute_map_false_positive_without_matching_ground_truth_is_penalized() -> None:
    gt = {"img1": [GroundTruthBox(defect_type="short", bbox=(0.3, 0.3, 0.7, 0.7))]}
    preds = {
        "img1": [
            # Confidently wrong: predicted well away from the only ground-truth box.
            RawDetection(defect_type="short", confidence=0.95, bbox=_bbox(0.0, 0.0, 0.1, 0.1))
        ]
    }

    map50, _map50_95, per_class = compute_map(preds, gt, CLASSES)

    assert map50 == pytest.approx(0.0)
    assert per_class["short"] == pytest.approx(0.0)


def test_compute_map_lower_iou_overlap_scores_between_zero_and_one_at_50_but_zero_at_95() -> None:
    # ~0.53 IoU with the ground truth — clears the 0.50 threshold but not tighter ones.
    gt = {"img1": [GroundTruthBox(defect_type="short", bbox=(0.30, 0.30, 0.70, 0.70))]}
    preds = {
        "img1": [
            RawDetection(defect_type="short", confidence=0.9, bbox=_bbox(0.34, 0.34, 0.74, 0.74))
        ]
    }

    map50, map50_95, per_class = compute_map(preds, gt, CLASSES)

    assert per_class["short"] == pytest.approx(1.0)  # AP@50 — the box clears IoU>=0.5
    assert map50 == pytest.approx(1.0)
    assert map50_95 < map50  # stricter thresholds in the 0.5-0.95 sweep aren't all cleared


def test_compute_map_excludes_classes_with_no_ground_truth_from_the_average() -> None:
    gt = {"img1": [GroundTruthBox(defect_type="short", bbox=(0.3, 0.3, 0.7, 0.7))]}
    preds = {
        "img1": [RawDetection(defect_type="short", confidence=0.9, bbox=_bbox(0.3, 0.3, 0.7, 0.7))]
    }

    map50, _map50_95, per_class = compute_map(preds, gt, CLASSES)

    # Only "short" has ground truth — it alone drives the average, not a 6-way split.
    assert map50 == pytest.approx(1.0)
    for other in CLASSES:
        if other != "short":
            assert per_class[other] == pytest.approx(0.0)


def test_compute_map_raises_when_golden_set_has_no_ground_truth_at_all() -> None:
    with pytest.raises(ApiError) as exc_info:
        compute_map({"img1": []}, {"img1": []}, CLASSES)
    assert exc_info.value.code == "GOLDEN_SET_EMPTY"


# --- manifest / label loading -------------------------------------------------------------


def test_load_manifest_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(ApiError) as exc_info:
        load_manifest(tmp_path / "does-not-exist")
    assert exc_info.value.code == "GOLDEN_SET_NOT_CONFIGURED"


def test_load_manifest_with_no_images_raises(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text('{"version": "gs-1", "classes": [], "images": []}')
    with pytest.raises(ApiError) as exc_info:
        load_manifest(tmp_path)
    assert exc_info.value.code == "GOLDEN_SET_EMPTY"


def test_load_manifest_parses_entries(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        '{"version": "gs-1", "classes": ["short"], '
        '"images": [{"image": "images/a.jpg", "label": "labels/a.txt"}]}'
    )

    manifest = load_manifest(tmp_path)

    assert manifest.version == "gs-1"
    assert manifest.classes == ["short"]
    assert manifest.images[0].image_path == tmp_path / "images/a.jpg"
    assert manifest.images[0].label_path == tmp_path / "labels/a.txt"


def test_load_ground_truth_parses_yolo_format(tmp_path: Path) -> None:
    label_path = tmp_path / "a.txt"
    label_path.write_text("3 0.5 0.5 0.4 0.4\n")

    boxes = load_ground_truth(label_path, CLASSES)

    assert len(boxes) == 1
    assert boxes[0].defect_type == "short"  # index 3 in DefectType's declared order
    assert boxes[0].bbox == pytest.approx((0.3, 0.3, 0.7, 0.7))


def test_load_ground_truth_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_ground_truth(tmp_path / "missing.txt", CLASSES) == []


# --- Real inference code path (FR-12's "Evaluation Is Real") ------------------------------


def test_evaluate_weights_runs_real_detect_against_golden_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uses the same `inference_backend == "fake"` deterministic stand-in as
    `test_inference.py` (always reports one `short` box at [0.3,0.3,0.7,0.7]) so this proves
    `evaluate_weights` genuinely runs `app.inference.detect.detect()` — the identical function
    `app.inference.service.process_image` calls in production — rather than a stubbed metric.
    """
    image_path = tmp_path / "images" / "a.jpg"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (100, 100), (10, 20, 30)).save(image_path, format="JPEG")
    label_path = tmp_path / "labels" / "a.txt"
    label_path.parent.mkdir(parents=True)
    label_path.write_text("3 0.5 0.5 0.4 0.4\n")  # class idx 3 == "short", matches the fake box
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "version": "gs-1",
                "classes": CLASSES,
                "images": [{"image": "images/a.jpg", "label": "labels/a.txt"}],
            }
        )
    )

    fake_settings = get_settings().model_copy(update={"inference_backend": "fake"})
    monkeypatch.setattr("app.inference.model.get_settings", lambda: fake_settings)

    manifest = load_manifest(tmp_path)
    metrics = evaluate_weights("/weights/whatever.pt", manifest)

    assert metrics.map50 == pytest.approx(1.0)
    assert metrics.per_class["short"] == pytest.approx(1.0)
    assert metrics.golden_set_version == "gs-1"
    assert metrics.image_count == 1
