import pytest

from app.inspections.state import InvalidTransitionError, mark_failed, transition
from app.models.enums import ImageStatus
from app.models.inspection_image import InspectionImage


def _image(status: ImageStatus = ImageStatus.QUEUED) -> InspectionImage:
    return InspectionImage(
        source="watch_folder",
        original_path="/data/watch-root/BATCH-1/board-1.jpg",
        checksum_sha256="deadbeef",
        status=status,
    )


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (ImageStatus.QUEUED, ImageStatus.PROCESSING),
        (ImageStatus.PROCESSING, ImageStatus.DETECTED),
        (ImageStatus.PROCESSING, ImageStatus.COMPLETED),
        (ImageStatus.DETECTED, ImageStatus.ANALYZING),
        (ImageStatus.DETECTED, ImageStatus.COMPLETED),
        (ImageStatus.ANALYZING, ImageStatus.COMPLETED),
        (ImageStatus.COMPLETED, ImageStatus.ANALYZING),
        (ImageStatus.FAILED, ImageStatus.QUEUED),
    ],
)
def test_valid_transitions_are_applied(start: ImageStatus, target: ImageStatus) -> None:
    image = _image(start)
    transition(image, target)
    assert image.status == target


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (ImageStatus.QUEUED, ImageStatus.DETECTED),
        (ImageStatus.QUEUED, ImageStatus.COMPLETED),
        (ImageStatus.PROCESSING, ImageStatus.QUEUED),
        (ImageStatus.DETECTED, ImageStatus.PROCESSING),
        (ImageStatus.ANALYZING, ImageStatus.DETECTED),
        (ImageStatus.COMPLETED, ImageStatus.PROCESSING),
        (ImageStatus.COMPLETED, ImageStatus.FAILED),
        (ImageStatus.FAILED, ImageStatus.PROCESSING),
        (ImageStatus.FAILED, ImageStatus.COMPLETED),
    ],
)
def test_invalid_transitions_are_rejected(start: ImageStatus, target: ImageStatus) -> None:
    image = _image(start)
    with pytest.raises(InvalidTransitionError):
        transition(image, target)
    assert image.status == start  # rejected transition never mutates state


def test_failed_requires_a_reason() -> None:
    image = _image(ImageStatus.PROCESSING)
    with pytest.raises(ValueError, match="failure_reason"):
        transition(image, ImageStatus.FAILED)


def test_transition_to_failed_persists_reason_and_sets_processed_at() -> None:
    image = _image(ImageStatus.PROCESSING)
    transition(image, ImageStatus.FAILED, failure_reason="disk I/O error")
    assert image.status == ImageStatus.FAILED
    assert image.failure_reason == "disk I/O error"
    assert image.processed_at is not None


def test_reingestion_clears_the_stale_failure_reason_and_processed_at() -> None:
    image = _image(ImageStatus.PROCESSING)
    transition(image, ImageStatus.FAILED, failure_reason="corrupted file")
    transition(image, ImageStatus.QUEUED)
    assert image.status == ImageStatus.QUEUED
    assert image.failure_reason is None
    assert image.processed_at is None  # otherwise looks like it already finished processing


def test_mark_failed_works_from_any_non_terminal_status() -> None:
    non_terminal = (
        ImageStatus.QUEUED,
        ImageStatus.PROCESSING,
        ImageStatus.DETECTED,
        ImageStatus.ANALYZING,
    )
    for start in non_terminal:
        image = _image(start)
        mark_failed(image, "boom")
        assert image.status == ImageStatus.FAILED
        assert image.failure_reason == "boom"


def test_mark_failed_rejects_completed() -> None:
    image = _image(ImageStatus.COMPLETED)
    with pytest.raises(InvalidTransitionError):
        mark_failed(image, "too late")
