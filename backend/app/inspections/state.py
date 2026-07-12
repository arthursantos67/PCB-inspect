"""InspectionImage status state machine (FR-04): QUEUED -> PROCESSING -> DETECTED ->
ANALYZING -> COMPLETED | FAILED.

`ANALYZING` only occurs when the agent chain is triggered (FR-06); otherwise `DETECTED`
goes straight to `COMPLETED`. `FAILED` is reachable from any non-terminal stage (a stage
failure can happen at any point in the pipeline, section 3.5) and `FAILED -> QUEUED` is
allowed so an operator can re-ingest once the cause is fixed (section 3.5), without ever
touching the file on disk.

`COMPLETED -> ANALYZING` is also allowed (issue #31): the `on_demand` agent-analysis endpoint
(`POST /api/v1/inspections/{id}/agent-analysis`) re-opens an already-completed, baseline-only
inspection to run the Analyst/Reviewer/Summarizer chain against it — the only way back into a
non-terminal status from COMPLETED, and only for that one target.
"""

from datetime import UTC, datetime

from app.models.enums import ImageStatus
from app.models.inspection_image import InspectionImage

_TERMINAL_STATUSES = frozenset({ImageStatus.COMPLETED, ImageStatus.FAILED})

ALLOWED_TRANSITIONS: dict[ImageStatus, frozenset[ImageStatus]] = {
    ImageStatus.QUEUED: frozenset({ImageStatus.PROCESSING, ImageStatus.FAILED}),
    ImageStatus.PROCESSING: frozenset(
        {ImageStatus.DETECTED, ImageStatus.COMPLETED, ImageStatus.FAILED}
    ),
    ImageStatus.DETECTED: frozenset(
        {ImageStatus.ANALYZING, ImageStatus.COMPLETED, ImageStatus.FAILED}
    ),
    ImageStatus.ANALYZING: frozenset({ImageStatus.COMPLETED, ImageStatus.FAILED}),
    ImageStatus.COMPLETED: frozenset({ImageStatus.ANALYZING}),
    ImageStatus.FAILED: frozenset({ImageStatus.QUEUED}),
}


class InvalidTransitionError(Exception):
    def __init__(self, current: ImageStatus, target: ImageStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition InspectionImage from {current} to {target}")


def transition(
    image: InspectionImage, to: ImageStatus, *, failure_reason: str | None = None
) -> None:
    """Applies `image.status = to` if the transition is allowed, raising
    `InvalidTransitionError` otherwise. Does not commit — the caller owns the session.
    """
    if to not in ALLOWED_TRANSITIONS[image.status]:
        raise InvalidTransitionError(image.status, to)

    if to is ImageStatus.FAILED:
        if not failure_reason:
            raise ValueError("failure_reason is required when transitioning to FAILED")
        image.failure_reason = failure_reason
    else:
        # Leaving a terminal status behind (re-ingestion from FAILED, or on-demand
        # reprocessing from COMPLETED) clears the stale reason/timestamp — both look like
        # "already finished" state that no longer applies once the image is back in flight.
        image.failure_reason = None
        image.processed_at = None

    image.status = to
    if to in _TERMINAL_STATUSES:
        image.processed_at = datetime.now(UTC)


def mark_failed(image: InspectionImage, reason: str) -> None:
    """Convenience wrapper: FAILED is reachable from every non-terminal status, so callers
    that just want "this stage blew up" don't need to know which status the image was in.
    `transition()` already rejects COMPLETED -> FAILED on its own (COMPLETED has no allowed
    outgoing transitions), so there's no need to special-case it here.
    """
    if image.status is ImageStatus.FAILED:
        image.failure_reason = reason
        return
    transition(image, ImageStatus.FAILED, failure_reason=reason)
