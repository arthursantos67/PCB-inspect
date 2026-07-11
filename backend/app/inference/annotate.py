"""Writes the annotated image (RV-04): bounding boxes with class + confidence, drawn over a
copy of the original and saved to the local app-data directory. Only called for images with
at least one reportable detection — the no-defect path (FR-05) never generates one.
"""

import uuid
from pathlib import Path

from PIL import Image, ImageDraw

from app.inference.detect import RawDetection

_BOX_COLOR = (220, 30, 30)
_LABEL_BG = (220, 30, 30)
_LABEL_FG = (255, 255, 255)


def write_annotated_image(
    *,
    source_path: Path,
    detections: list[RawDetection],
    app_data_dir: Path,
    image_id: uuid.UUID,
) -> Path:
    annotated_dir = app_data_dir / "annotated"
    annotated_dir.mkdir(parents=True, exist_ok=True)
    dest = annotated_dir / f"{image_id}.jpg"

    with Image.open(source_path) as source:
        canvas = source.convert("RGB")
        width, height = canvas.size
        draw = ImageDraw.Draw(canvas)

        for det in detections:
            x1 = det.bbox["x1"] * width
            y1 = det.bbox["y1"] * height
            x2 = det.bbox["x2"] * width
            y2 = det.bbox["y2"] * height
            draw.rectangle([x1, y1, x2, y2], outline=_BOX_COLOR, width=2)

            label = f"{det.defect_type} {det.confidence:.2f}"
            text_bbox = draw.textbbox((0, 0), label)
            text_w, text_h = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
            label_y = max(y1 - text_h - 4, 0)
            draw.rectangle([x1, label_y, x1 + text_w + 4, label_y + text_h + 4], fill=_LABEL_BG)
            draw.text((x1 + 2, label_y + 2), label, fill=_LABEL_FG)

        canvas.save(dest, format="JPEG")

    return dest
