"""Dataset export generation task (FR-18, Issue 36) — the real path. Runs
`generate_dataset_export` via `.apply()` (eager execution, no Redis broker in the test
environment) directly against `task_db_session()`, same convention as
`test_report_generation.py`.

The round-trip check doesn't stop at "the zip has files in it": every exported image/label pair
is re-parsed with `ultralytics.data.utils.verify_image_label` — the exact function
`YOLODataset` uses to validate a label file before training — so a malformed bbox, a class index
out of range, or a mismatched image/label pairing would fail here the same way it would in a real
training run.
"""

import asyncio
import json
import uuid
import zipfile
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from sqlalchemy import text
from ultralytics.data.utils import verify_image_label

from app.core.security import hash_password
from app.datasets.exporter import CLASS_NAMES
from app.models import DatasetExport, Detection, InspectionImage, ModelVersion, SystemConfig, User
from app.models.enums import (
    DatasetExportStatus,
    DefectType,
    DetectionReview,
    DetectionSource,
    ImageSource,
    ImageStatus,
)
from app.tasks.dataset_exports import generate_dataset_export
from app.tasks.db import task_db_session

_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


async def _create_user() -> uuid.UUID:
    async with task_db_session() as db:
        user = User(
            email=f"{uuid.uuid4()}@pcb-inspect.local",
            password_hash=hash_password("correct-horse-battery"),
            full_name="Operator",
        )
        db.add(user)
        await db.commit()
        return user.id


async def _set_reports_output_dir(path: Path) -> None:
    async with task_db_session() as db:
        db.add(SystemConfig(key="reports_output_dir", value=str(path)))
        await db.commit()


async def _create_dataset_export(
    *, requested_by: uuid.UUID, filters: dict[str, Any] | None = None
) -> uuid.UUID:
    async with task_db_session() as db:
        export = DatasetExport(filters=filters, requested_by=requested_by)
        db.add(export)
        await db.commit()
        return export.id


async def _get_dataset_export(export_id: uuid.UUID) -> DatasetExport | None:
    async with task_db_session() as db:
        return await db.get(DatasetExport, export_id)


def _write_jpeg(path: Path, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (100, 100), color).save(path, format="JPEG")


async def _seed_detections(image_dir: Path) -> dict[str, Any]:
    """Five images exercising every category FR-18 cares about:

    - `image_confirmed_v1`: one CONFIRMED, model-sourced detection (model v1) -> labeled.
    - `image_mixed_v2`: a CONFIRMED SPUR (model v2) + a FALSE_POSITIVE SHORT (model v1) on the
      same image -> only the confirmed one becomes a label line.
    - `image_manual`: a manual annotation only (source=manual, pre-confirmed, no model) ->
      labeled, no model version.
    - `image_unreviewed`: one UNREVIEWED detection only -> excluded from the export entirely.
    - `image_old`: a CONFIRMED detection dated well before the others -> for period filtering.
    """
    async with task_db_session() as db:
        model_v1 = ModelVersion(version=f"v1-{uuid.uuid4().hex[:8]}", weights_path="/w/v1.pt")
        model_v2 = ModelVersion(version=f"v2-{uuid.uuid4().hex[:8]}", weights_path="/w/v2.pt")
        db.add_all([model_v1, model_v2])
        await db.flush()

        def _make_image(name: str, created_at: datetime) -> InspectionImage:
            path = image_dir / f"{name}.jpg"
            _write_jpeg(path, (10, 20, 30))
            image = InspectionImage(
                source=ImageSource.WATCH_FOLDER,
                original_path=str(path),
                checksum_sha256=uuid.uuid4().hex,
                status=ImageStatus.COMPLETED,
                created_at=created_at,
            )
            db.add(image)
            return image

        image_confirmed = _make_image("image_confirmed_v1", _NOW)
        image_mixed = _make_image("image_mixed_v2", _NOW)
        image_manual = _make_image("image_manual", _NOW)
        image_unreviewed = _make_image("image_unreviewed", _NOW)
        image_old = _make_image("image_old", _NOW - timedelta(days=365))
        await db.flush()

        db.add(
            Detection(
                image_id=image_confirmed.id,
                defect_type=DefectType.MOUSE_BITE,
                bbox={"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.5},
                confidence=Decimal("0.900"),
                is_reported=True,
                model_version_id=model_v1.id,
                review=DetectionReview.CONFIRMED,
            )
        )
        db.add(
            Detection(
                image_id=image_mixed.id,
                defect_type=DefectType.SPUR,
                bbox={"x1": 0.2, "y1": 0.2, "x2": 0.3, "y2": 0.3},
                confidence=Decimal("0.850"),
                is_reported=True,
                model_version_id=model_v2.id,
                review=DetectionReview.CONFIRMED,
            )
        )
        db.add(
            Detection(
                image_id=image_mixed.id,
                defect_type=DefectType.SHORT,
                bbox={"x1": 0.5, "y1": 0.5, "x2": 0.6, "y2": 0.6},
                confidence=Decimal("0.700"),
                is_reported=True,
                model_version_id=model_v1.id,
                review=DetectionReview.FALSE_POSITIVE,
            )
        )
        db.add(
            Detection(
                image_id=image_manual.id,
                defect_type=DefectType.OPEN_CIRCUIT,
                bbox={"x1": 0.05, "y1": 0.05, "x2": 0.2, "y2": 0.2},
                confidence=Decimal("1.000"),
                is_reported=True,
                model_version_id=None,
                source=DetectionSource.MANUAL,
                review=DetectionReview.CONFIRMED,
            )
        )
        db.add(
            Detection(
                image_id=image_unreviewed.id,
                defect_type=DefectType.SPURIOUS_COPPER,
                bbox={"x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.2},
                confidence=Decimal("0.600"),
                is_reported=True,
                model_version_id=model_v1.id,
                review=DetectionReview.UNREVIEWED,
            )
        )
        db.add(
            Detection(
                image_id=image_old.id,
                defect_type=DefectType.MOUSE_BITE,
                bbox={"x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.2},
                confidence=Decimal("0.900"),
                is_reported=True,
                model_version_id=model_v1.id,
                review=DetectionReview.CONFIRMED,
            )
        )

        await db.commit()
        return {
            "model_v1": model_v1.version,
            "model_v2": model_v2.version,
            "image_confirmed": image_confirmed.id,
            "image_mixed": image_mixed.id,
            "image_manual": image_manual.id,
            "image_unreviewed": image_unreviewed.id,
            "image_old": image_old.id,
        }


_TABLES_IN_FK_ORDER = (
    "detection",
    "inspection_image",
    "model_version",
    "dataset_export",
    "system_config",
    '"user"',
)


def teardown_function() -> None:
    async def _truncate() -> None:
        async with task_db_session() as db:
            for table in _TABLES_IN_FK_ORDER:
                await db.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
            await db.commit()

    _run(_truncate())


def _extract_zip(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(dest)


def _verify_label(image_path: Path, label_path: Path) -> np.ndarray:
    """Runs the same per-item validation `YOLODataset.get_labels()` performs while caching a
    dataset for training — asserts it reports the pair as neither missing nor corrupt, and
    returns the parsed `(cls, x, y, w, h)` label rows.
    """
    args = (str(image_path), str(label_path), "", False, len(CLASS_NAMES), 0, 2, False)
    _im_file, lb, _shape, _segments, _keypoints, nm, _nf, _ne, nc, msg = verify_image_label(args)
    assert nc == 0, f"corrupt image/label pair: {msg}"
    assert nm == 0, f"label file missing: {msg}"
    return lb


# --- Full round trip: valid YOLO format, correct label handling, manifest accuracy ----------


def test_dataset_export_round_trip_yolo_format(tmp_path: Path) -> None:
    _run(_set_reports_output_dir(tmp_path / "reports"))
    image_dir = tmp_path / "source-images"
    image_dir.mkdir()
    seed = _run(_seed_detections(image_dir))
    user_id = _run(_create_user())

    export_id = _run(_create_dataset_export(requested_by=user_id))
    generate_dataset_export.apply(args=[str(export_id)])

    export = _run(_get_dataset_export(export_id))
    assert export is not None
    assert export.status == DatasetExportStatus.COMPLETED
    assert export.error_message is None
    assert export.file_path is not None
    zip_path = Path(export.file_path)
    assert zip_path.is_file()

    extracted = tmp_path / "extracted"
    _extract_zip(zip_path, extracted)

    manifest = export.manifest
    assert manifest is not None
    assert manifest == json.loads((extracted / "manifest.json").read_text())

    # The unreviewed-only image never participates in the export at all.
    image_files = {p.stem for p in (extracted / "images").iterdir()}
    assert image_files == {
        str(seed["image_confirmed"]),
        str(seed["image_mixed"]),
        str(seed["image_manual"]),
        str(seed["image_old"]),
    }
    assert str(seed["image_unreviewed"]) not in image_files

    # Every image/label pair loads as a standard YOLO training pipeline would load it.
    for stem in image_files:
        _verify_label(extracted / "images" / f"{stem}.jpg", extracted / "labels" / f"{stem}.txt")

    # image_confirmed: one MOUSE_BITE label.
    lb = _verify_label(
        extracted / "images" / f"{seed['image_confirmed']}.jpg",
        extracted / "labels" / f"{seed['image_confirmed']}.txt",
    )
    assert lb.shape == (1, 5)
    assert int(lb[0, 0]) == list(CLASS_NAMES).index(DefectType.MOUSE_BITE.value)

    # image_mixed: only the CONFIRMED spur becomes a label; the false-positive short is excluded.
    lb = _verify_label(
        extracted / "images" / f"{seed['image_mixed']}.jpg",
        extracted / "labels" / f"{seed['image_mixed']}.txt",
    )
    assert lb.shape == (1, 5)
    assert int(lb[0, 0]) == list(CLASS_NAMES).index(DefectType.SPUR.value)

    # image_manual: the manually-annotated defect appears with its assigned class.
    lb = _verify_label(
        extracted / "images" / f"{seed['image_manual']}.jpg",
        extracted / "labels" / f"{seed['image_manual']}.txt",
    )
    assert lb.shape == (1, 5)
    assert int(lb[0, 0]) == list(CLASS_NAMES).index(DefectType.OPEN_CIRCUIT.value)

    # Manifest statistics match the actual exported file counts exactly (image_confirmed,
    # image_mixed's spur, image_manual, and image_old are all CONFIRMED -> 4 labels; image_mixed's
    # short is the lone FALSE_POSITIVE, excluded from labels/ but not from the statistics).
    assert manifest["statistics"]["image_count"] == 4
    assert manifest["statistics"]["label_count"] == 4
    assert manifest["statistics"]["by_defect_type"] == {
        DefectType.MOUSE_BITE.value: 2,  # image_confirmed + image_old
        DefectType.SPUR.value: 1,
        DefectType.OPEN_CIRCUIT.value: 1,
    }
    assert manifest["statistics"]["by_review_status"] == {
        DetectionReview.CONFIRMED.value: 4,
        DetectionReview.FALSE_POSITIVE.value: 1,
    }

    # Traceable to the model version(s) that produced the exported detections (RV-05) — the
    # manual annotation contributes no model version.
    exported_versions = {row["version"] for row in manifest["model_versions"]}
    assert exported_versions == {seed["model_v1"], seed["model_v2"]}

    assert manifest["classes"] == list(CLASS_NAMES)
    assert (extracted / "data.yaml").is_file()


# --- Filters narrow the export exactly, no over- or under-inclusion ------------------------


def test_dataset_export_defect_type_and_review_status_filters_narrow_exactly(
    tmp_path: Path,
) -> None:
    _run(_set_reports_output_dir(tmp_path / "reports"))
    image_dir = tmp_path / "source-images"
    image_dir.mkdir()
    seed = _run(_seed_detections(image_dir))
    user_id = _run(_create_user())

    export_id = _run(
        _create_dataset_export(
            requested_by=user_id,
            filters={"defect_type": [DefectType.SHORT.value], "review_status": ["false_positive"]},
        )
    )
    generate_dataset_export.apply(args=[str(export_id)])

    export = _run(_get_dataset_export(export_id))
    assert export is not None
    assert export.status == DatasetExportStatus.COMPLETED

    extracted = tmp_path / "extracted"
    _extract_zip(Path(export.file_path), extracted)

    # Only image_mixed has a `short` detection at all, and it's the false-positive one — the
    # image is included (as a background sample) but contributes zero labels.
    image_files = {p.stem for p in (extracted / "images").iterdir()}
    assert image_files == {str(seed["image_mixed"])}
    assert (extracted / "labels" / f"{seed['image_mixed']}.txt").read_text() == ""

    assert export.manifest["statistics"]["image_count"] == 1
    assert export.manifest["statistics"]["label_count"] == 0
    assert export.manifest["statistics"]["by_review_status"] == {
        DetectionReview.CONFIRMED.value: 0,
        DetectionReview.FALSE_POSITIVE.value: 1,
    }


def test_dataset_export_period_filter_excludes_out_of_range_images(tmp_path: Path) -> None:
    _run(_set_reports_output_dir(tmp_path / "reports"))
    image_dir = tmp_path / "source-images"
    image_dir.mkdir()
    seed = _run(_seed_detections(image_dir))
    user_id = _run(_create_user())

    export_id = _run(
        _create_dataset_export(
            requested_by=user_id,
            filters={"date_from": (_NOW - timedelta(days=1)).isoformat()},
        )
    )
    generate_dataset_export.apply(args=[str(export_id)])

    export = _run(_get_dataset_export(export_id))
    assert export.status == DatasetExportStatus.COMPLETED

    extracted = tmp_path / "extracted"
    _extract_zip(Path(export.file_path), extracted)
    image_files = {p.stem for p in (extracted / "images").iterdir()}

    # image_old is dated a year before date_from and must be excluded.
    assert str(seed["image_old"]) not in image_files
    assert str(seed["image_confirmed"]) in image_files
    assert export.manifest["statistics"]["image_count"] == 3


# --- Never crash the worker on a bad export -------------------------------------------------


def test_dataset_export_with_missing_source_image_fails_gracefully(tmp_path: Path) -> None:
    _run(_set_reports_output_dir(tmp_path / "reports"))
    image_dir = tmp_path / "source-images"
    image_dir.mkdir()
    user_id = _run(_create_user())

    async def _seed_with_missing_file() -> None:
        async with task_db_session() as db:
            image = InspectionImage(
                source=ImageSource.WATCH_FOLDER,
                original_path=str(image_dir / "does-not-exist.jpg"),
                checksum_sha256=uuid.uuid4().hex,
                status=ImageStatus.COMPLETED,
                created_at=_NOW,
            )
            db.add(image)
            await db.flush()
            db.add(
                Detection(
                    image_id=image.id,
                    defect_type=DefectType.MOUSE_BITE,
                    bbox={"x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.2},
                    confidence=Decimal("0.900"),
                    is_reported=True,
                    review=DetectionReview.CONFIRMED,
                )
            )
            await db.commit()

    _run(_seed_with_missing_file())

    export_id = _run(_create_dataset_export(requested_by=user_id))
    generate_dataset_export.apply(args=[str(export_id)])

    export = _run(_get_dataset_export(export_id))
    assert export is not None
    assert export.status == DatasetExportStatus.FAILED
    assert export.error_message is not None
    assert export.file_path is None
