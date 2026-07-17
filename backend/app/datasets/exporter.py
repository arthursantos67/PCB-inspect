"""Assembles a labeled dataset in YOLO format from reviewed detections (FR-18) — the input to
the continuous-improvement loop described in PRD sections 4.3/17: retraining itself stays
external, this only prepares the labeled data.

Confirmed detections (`Detection.review == confirmed`) keep their label; false-positive
corrections (`review == false_positive`) are excluded from `labels/` but the image is still
exported (a hard-negative/background sample YOLO training pipelines handle natively via an
empty label file); manual annotations (FR-10, `source == manual`) are already pre-confirmed at
creation time, so they need no special-casing here — they fall out of the same "confirmed"
branch as model-sourced detections. Class indices are the fixed `DefectType` enum declaration
order, independent of any `defect_type` filter, so ids stay stable across exports.
"""

import json
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.datasets.filters import DatasetExportFilters, matching_detections_query
from app.datasets.schemas import DatasetExportFiltersIn
from app.models import DatasetExport, Detection, InspectionImage, ModelVersion
from app.models.enums import DefectType, DetectionReview

CLASS_NAMES: tuple[str, ...] = tuple(member.value for member in DefectType)
_CLASS_INDEX: dict[DefectType, int] = {member: index for index, member in enumerate(DefectType)}


@dataclass
class GenerationResult:
    file_path: Path
    manifest: dict[str, Any]


def _yolo_label_line(detection: Detection) -> str:
    bbox = detection.bbox
    x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]
    x_center = (x1 + x2) / 2
    y_center = (y1 + y2) / 2
    width = x2 - x1
    height = y2 - y1
    class_index = _CLASS_INDEX[detection.defect_type]
    return f"{class_index} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}"


def _data_yaml(class_names: tuple[str, ...]) -> str:
    """Minimal `data.yaml` (Ultralytics convention) so the exported package is trainable as-is,
    without the operator having to hand-write one from the manifest's `classes` list.
    """
    lines = ["path: .", "train: images", "val: images", f"nc: {len(class_names)}", "names:"]
    lines.extend(f"  {index}: {name}" for index, name in enumerate(class_names))
    return "\n".join(lines) + "\n"


def _output_path(output_dir: Path, export_id: uuid.UUID) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"dataset-export-{export_id}.zip"


async def generate(db: AsyncSession, export: DatasetExport, output_dir: Path) -> GenerationResult:
    filters_in = DatasetExportFiltersIn.model_validate(export.filters or {})
    filters = DatasetExportFilters(**filters_in.model_dump())
    rows = (await db.execute(matching_detections_query(filters))).all()

    detections_by_image: dict[uuid.UUID, list[Detection]] = {}
    images_by_id: dict[uuid.UUID, InspectionImage] = {}
    for detection, image in rows:
        detections_by_image.setdefault(image.id, []).append(detection)
        images_by_id[image.id] = image

    by_defect_type: dict[str, int] = {}
    by_review_status: dict[str, int] = {
        DetectionReview.CONFIRMED.value: 0,
        DetectionReview.FALSE_POSITIVE.value: 0,
    }
    model_version_ids: set[uuid.UUID] = set()
    label_count = 0

    path = _output_path(output_dir, export.id)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for image_id, detections in detections_by_image.items():
            image = images_by_id[image_id]
            source_path = Path(image.original_path)
            extension = source_path.suffix.lstrip(".") or "jpg"
            archive.write(source_path, f"images/{image_id}.{extension}")

            label_lines: list[str] = []
            for detection in detections:
                by_review_status[detection.review.value] = (
                    by_review_status.get(detection.review.value, 0) + 1
                )
                if detection.model_version_id is not None:
                    model_version_ids.add(detection.model_version_id)
                if detection.review is DetectionReview.CONFIRMED:
                    label_lines.append(_yolo_label_line(detection))
                    by_defect_type[detection.defect_type.value] = (
                        by_defect_type.get(detection.defect_type.value, 0) + 1
                    )
                    label_count += 1
            # An image with only false-positive corrections still gets a label file — empty,
            # a valid YOLO "background/no objects" sample — rather than being left unpaired.
            content = "\n".join(label_lines)
            archive.writestr(f"labels/{image_id}.txt", f"{content}\n" if content else "")

        model_versions: list[dict[str, str]] = []
        if model_version_ids:
            versions = (
                (
                    await db.execute(
                        select(ModelVersion).where(ModelVersion.id.in_(model_version_ids))
                    )
                )
                .scalars()
                .all()
            )
            model_versions = [
                {"id": str(version.id), "version": version.version} for version in versions
            ]

        manifest: dict[str, Any] = {
            "export_id": str(export.id),
            "filters": export.filters or {},
            "classes": list(CLASS_NAMES),
            "statistics": {
                "image_count": len(detections_by_image),
                "label_count": label_count,
                "by_defect_type": by_defect_type,
                "by_review_status": by_review_status,
            },
            # Source model version(s) the exported detections came from (RV-05 traceability) —
            # empty when every exported detection is a manual annotation (no producing model).
            "model_versions": model_versions,
        }
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        archive.writestr("data.yaml", _data_yaml(CLASS_NAMES))

    return GenerationResult(file_path=path, manifest=manifest)
