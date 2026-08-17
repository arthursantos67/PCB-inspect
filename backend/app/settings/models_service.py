"""Model version registration (by upload or by local path), golden-set evaluation triggering,
and the activation gate (FR-12, NFR-05, RN-02, RN-10).
"""

import asyncio
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.core.config import get_settings
from app.core.errors import ApiError
from app.models import ModelVersion
from app.models.enums import ModelEvaluationStatus

# NFR-05 — fixed precision floor for the active model, not one of FR-13's operator-tunable
# runtime values: loosening it is exactly the kind of change that should require touching
# code/review, not a config PATCH.
MAP50_FLOOR = 0.95

# Version strings become the stored weights file's own name, so they are restricted to
# characters that can't walk out of the weights directory or collide with a shell/OS quirk.
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# The operator uploads the `.pt` file the training notebook produced.
# `best.pt` for the current architecture is ~114 MB; the cap is generous enough for a
# larger backbone while still refusing to fill the disk with something that isn't a model.
MAX_WEIGHTS_UPLOAD_BYTES = 1024 * 1024 * 1024
_UPLOAD_CHUNK_BYTES = 1024 * 1024

# A torch checkpoint saved by any currently supported torch is a ZIP archive; `\x80` opens the
# legacy pickle format that older `torch.save` produced, still loadable by `torch.load`. Read
# from the file's own header rather than trusting the extension, same rule ingestion applies to
# images (`app.ingestion.validation`).
_WEIGHTS_MAGIC_PREFIXES = (b"PK\x03\x04", b"\x80")


class UploadedFile(Protocol):
    """The slice of FastAPI's `UploadFile` this module needs — kept structural so the service
    layer stays framework-free and the upload path is testable without an HTTP client.
    """

    async def read(self, size: int = -1) -> bytes: ...


def validate_weights_path(path: Path) -> None:
    if not path.exists():
        raise ApiError("PATH_NOT_FOUND", f"Weights file does not exist: {path}", 422)
    if not path.is_file():
        raise ApiError("PATH_NOT_FOUND", f"Weights path is not a file: {path}", 422)
    if not os.access(path, os.R_OK):
        raise ApiError("PATH_NOT_READABLE", f"Weights file is not readable: {path}", 422)


def validate_version_string(version: str) -> str:
    version = version.strip()
    if not _VERSION_PATTERN.fullmatch(version):
        raise ApiError(
            "VALIDATION_FAILED",
            "A version name may only use letters, numbers, dot, dash and underscore, and "
            "must start with a letter or a number.",
            422,
        )
    return version


async def ensure_version_available(db: AsyncSession, version: str) -> None:
    existing = await db.scalar(select(ModelVersion).where(ModelVersion.version == version))
    if existing is not None:
        raise ApiError(
            "MODEL_VERSION_EXISTS", f"Model version already registered: {version}", 409
        )


async def store_uploaded_weights(version: str, upload: UploadedFile) -> Path:
    """Streams an uploaded `.pt` file into the managed weights directory and returns where it
    landed, so the rest of registration is identical to registering a local path (FR-12).

    Copying is the point here, unlike ingestion, which only ever references images in place
    (FR-03): the weights the active version points at have to still be readable months later,
    and the file the operator picked lives wherever their browser downloaded it. Written under
    a `.part` name and renamed only once the whole body has been read, so an interrupted upload
    can never be registered as a model.
    """
    destination_dir = get_settings().uploaded_weights_dir
    await asyncio.to_thread(destination_dir.mkdir, parents=True, exist_ok=True)
    destination = destination_dir / f"{version}.pt"
    if await asyncio.to_thread(destination.exists):
        raise ApiError(
            "MODEL_VERSION_EXISTS",
            f"A weights file for version {version} is already stored.",
            409,
        )

    partial = destination.with_suffix(".pt.part")
    written = 0
    try:
        handle = await asyncio.to_thread(partial.open, "wb")
        try:
            while chunk := await upload.read(_UPLOAD_CHUNK_BYTES):
                if written == 0 and not chunk.startswith(_WEIGHTS_MAGIC_PREFIXES):
                    raise ApiError(
                        "VALIDATION_FAILED",
                        "That file is not a PyTorch weights file (.pt).",
                        422,
                    )
                written += len(chunk)
                if written > MAX_WEIGHTS_UPLOAD_BYTES:
                    raise ApiError(
                        "VALIDATION_FAILED",
                        "The weights file exceeds "
                        f"{MAX_WEIGHTS_UPLOAD_BYTES // (1024 * 1024)} MB.",
                        413,
                    )
                await asyncio.to_thread(handle.write, chunk)
        finally:
            await asyncio.to_thread(handle.close)

        if written == 0:
            raise ApiError("VALIDATION_FAILED", "The uploaded weights file is empty.", 422)
        await asyncio.to_thread(partial.rename, destination)
    except Exception:
        await asyncio.to_thread(partial.unlink, True)
        raise

    return destination


async def discard_uploaded_weights(path: Path) -> None:
    """Removes a file `store_uploaded_weights` wrote when registration never completed, so a
    failed upload doesn't leave an orphan taking up disk space no screen can point at.
    """
    await asyncio.to_thread(path.unlink, True)


async def register_model_version(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    version: str,
    weights_path: str,
    upload: bool = False,
) -> ModelVersion:
    """Creates the `ModelVersion` row (`evaluation_status=PENDING`, `metrics=None`) — the
    caller is responsible for enqueueing the golden-set evaluation task after commit
    (`app.settings.models_router`, mirroring ingestion's enqueue-after-commit pattern). The
    registration payload has no `metrics` field at all (RN-10, FR-12's "Evaluation Is Real"):
    there is no way to set them except the evaluation actually running.

    Both ways of registering weights (uploading the `.pt` file, or pointing at a path already
    on the machine) end up here, so there is exactly one evaluation gate to get through no
    matter how the file arrived.
    """
    await ensure_version_available(db, version)
    validate_weights_path(Path(weights_path))

    model_version = ModelVersion(
        version=version,
        weights_path=weights_path,
        evaluation_status=ModelEvaluationStatus.PENDING,
    )
    db.add(model_version)
    await db.flush()
    await record_audit(
        db,
        actor_id=actor_id,
        action="model.registered",
        entity_type="model_version",
        entity_id=model_version.id,
        payload={
            "version": version,
            "weights_path": weights_path,
            "source": "upload" if upload else "path",
        },
    )
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
