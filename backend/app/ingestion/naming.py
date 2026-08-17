"""Batch/board inference from the directory convention (FR-03).

Each immediate subdirectory of the scanned root is one batch (`batch_number` = subdirectory
name); each image file directly inside it is one board (`board_number` = filename stem).
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BatchBoard:
    batch_number: str
    board_number: str


# The accepted formats (FR-03). Anything else in a batch folder — OS junk like
# `.DS_Store`/`Thumbs.db`, spreadsheets, PDFs sitting next to the boards — is ignored here
# rather than ingested and then recorded as a failed file the operator has to read past.
# A file that *is* one of these but turns out to be corrupt still fails loudly, which is the
# case FR-03's "invalid file handling" is actually about.
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"})


def infer_batch_and_board(root: Path, file_path: Path) -> BatchBoard | None:
    """Returns None when `file_path` isn't one directory level under `root` — i.e. it sits
    directly in the root (no batch subdirectory) or deeper than one level of nesting.
    """
    try:
        relative = file_path.relative_to(root)
    except ValueError:
        return None

    parts = relative.parts
    if len(parts) != 2:
        return None

    batch_number, filename = parts
    return BatchBoard(batch_number=batch_number, board_number=Path(filename).stem)


def iter_batch_files(root: Path) -> list[Path]:
    """Every image one level under an immediate subdirectory of `root`, in a stable order."""
    files: list[Path] = []
    for batch_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        files.extend(
            sorted(
                p for p in batch_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
            )
        )
    return files
