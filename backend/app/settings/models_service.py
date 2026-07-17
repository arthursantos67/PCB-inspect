"""Model version registration, golden-set evaluation triggering, and the activation gate
(FR-12, NFR-05, RN-02, RN-10).
"""

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.core.errors import ApiError
from app.models import ModelVersion
from app.models.enums import ModelEvaluationStatus

# NFR-05 — fixed precision floor for the active model, not one of FR-13's operator-tunable
# runtime values: loosening it is exactly the kind of change that should require touching
# code/review, not a config PATCH.
MAP50_FLOOR = 0.95


def validate_weights_path(path: Path) -> None:
    if not path.exists():
        raise ApiError("PATH_NOT_FOUND", f"Weights file does not exist: {path}", 422)
    if not path.is_file():
        raise ApiError("PATH_NOT_FOUND", f"Weights path is not a file: {path}", 422)
    if not os.access(path, os.R_OK):
        raise ApiError("PATH_NOT_READABLE", f"Weights file is not readable: {path}", 422)


async def register_model_version(
    db: AsyncSession, *, version: str, weights_path: str
) -> ModelVersion:
    """Creates the `ModelVersion` row (`evaluation_status=PENDING`, `metrics=None`) — the
    caller is responsible for enqueueing the golden-set evaluation task after commit
    (`app.settings.models_router`, mirroring ingestion's enqueue-after-commit pattern). The
    registration payload has no `metrics` field at all (RN-10, FR-12's "Evaluation Is Real"):
    there is no way to set them except the evaluation actually running.
    """
    existing = await db.scalar(select(ModelVersion).where(ModelVersion.version == version))
    if existing is not None:
        raise ApiError(
            "MODEL_VERSION_EXISTS", f"Model version already registered: {version}", 409
        )

    validate_weights_path(Path(weights_path))

    model_version = ModelVersion(
        version=version,
        weights_path=weights_path,
        evaluation_status=ModelEvaluationStatus.PENDING,
    )
    db.add(model_version)
    await db.commit()
    await db.refresh(model_version)
    return model_version


async def list_model_versions(db: AsyncSession) -> list[ModelVersion]:
    result = await db.scalars(select(ModelVersion).order_by(ModelVersion.created_at.desc()))
    return list(result)


async def get_model_version(db: AsyncSession, model_version_id: uuid.UUID) -> ModelVersion:
    model_version = await db.get(ModelVersion, model_version_id)
    if model_version is None:
        raise ApiError("RESOURCE_NOT_FOUND", "Model version not found.", 404)
    return model_version


async def activate_model_version(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID,
    model_version_id: uuid.UUID,
    override: bool,
    justification: str | None,
) -> ModelVersion:
    """Activation gate (FR-12, NFR-05, RN-10): blocked while evaluation hasn't completed,
    blocked below the mAP@50 floor unless explicitly, auditably overridden (FR-16). Swaps
    `is_active` old->new within this same transaction so RN-02's partial unique index is
    exercised by real traffic, not bypassed — the previous active row is always deactivated
    with its own `UPDATE` before the new one is activated, so the two `is_active=true` values
    never coexist even momentarily.
    """
    model_version = await get_model_version(db, model_version_id)

    if model_version.evaluation_status != ModelEvaluationStatus.COMPLETED:
        raise ApiError(
            "MODEL_ACTIVATION_FAILED",
            "Golden-set evaluation has not completed for this version.",
            422,
            details={"evaluation_status": model_version.evaluation_status.value},
        )

    metrics = model_version.metrics or {}
    map50 = float(metrics.get("map50", 0.0))
    below_floor = map50 < MAP50_FLOOR

    if below_floor and not override:
        raise ApiError(
            "MODEL_ACTIVATION_FAILED",
            f"mAP@50 {map50:.4f} is below the required floor {MAP50_FLOOR:.2f}.",
            422,
            details={"map50": map50, "floor": MAP50_FLOOR},
        )
    if below_floor and override and not (justification and justification.strip()):
        raise ApiError(
            "VALIDATION_FAILED",
            "A justification is required to override the mAP@50 floor.",
            400,
        )

    previously_active = await db.scalar(
        select(ModelVersion).where(ModelVersion.is_active.is_(True))
    )
    if previously_active is not None and previously_active.id != model_version.id:
        previously_active.is_active = False
        await db.flush()

    now = datetime.now(UTC)
    model_version.is_active = True
    model_version.activated_at = now
    await db.flush()

    await record_audit(
        db,
        actor_id=actor_id,
        action="model.activated",
        entity_type="model_version",
        entity_id=model_version.id,
        payload={
            "version": model_version.version,
            "map50": map50,
            "floor": MAP50_FLOOR,
            "override": override and below_floor,
            "justification": justification if (override and below_floor) else None,
            "previous_version_id": (
                str(previously_active.id)
                if previously_active is not None and previously_active.id != model_version.id
                else None
            ),
        },
    )
    await db.commit()
    await db.refresh(model_version)
    return model_version
