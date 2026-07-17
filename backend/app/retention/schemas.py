from pydantic import BaseModel


class RetentionPurgePreview(BaseModel):
    """What `POST /api/v1/retention/purge` (the beat-scheduled `purge_expired` task) would
    delete right now, given the current retention config — read-only (FR-17's dry-run mode).
    """

    cutoffs: dict[str, str]
    counts: dict[str, int]
