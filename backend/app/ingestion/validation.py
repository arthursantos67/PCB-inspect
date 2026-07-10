"""Format validation (by magic bytes, not extension) and checksumming for ingested files."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# Accepted formats (FR-03): JPG, PNG, TIFF, BMP. Keyed by Pillow's `Image.format`.
_ACCEPTED_PIL_FORMATS = {"JPEG": "jpg", "PNG": "png", "TIFF": "tiff", "BMP": "bmp"}

_CHECKSUM_CHUNK_SIZE = 1024 * 1024


class InvalidImageError(Exception):
    """Raised when a file is not a readable image in one of the accepted formats."""


@dataclass(frozen=True)
class ImageMetadata:
    format: str
    width: int
    height: int


def sha256_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHECKSUM_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_checksum_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_image_metadata(path: Path) -> ImageMetadata:
    """Identifies the format from the file's own header (magic bytes) and its dimensions.

    Raises InvalidImageError for unsupported formats, truncated files, or anything else
    Pillow can't decode — the caller records this against the file without touching it.
    """
    try:
        with Image.open(path) as img:
            image_format = img.format
            width, height = img.size
            img.load()  # forces full decode, catching truncated/corrupted pixel data too
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidImageError(str(exc)) from exc

    if image_format not in _ACCEPTED_PIL_FORMATS:
        raise InvalidImageError(f"unsupported format: {image_format}")

    return ImageMetadata(format=_ACCEPTED_PIL_FORMATS[image_format], width=width, height=height)
