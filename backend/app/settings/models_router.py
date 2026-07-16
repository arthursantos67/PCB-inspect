import asyncio
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models import User
from app.settings import models_service
from app.settings.models_schemas import (
    ModelEvaluationOut,
    ModelVersionActivateRequest,
    ModelVersionOut,
    ModelVersionRegisterRequest,
)
from app.tasks.models import reload_inference_model, run_model_evaluation

router = APIRouter(prefix="/api/v1/settings/models", tags=["models"])


@router.get("", response_model=list[ModelVersionOut])
async def list_models(
    db: AsyncSession = Depends(get_db), _current_user: User = Depends(get_current_user)
) -> list[ModelVersionOut]:
    versions = await models_service.list_model_versions(db)
    return [ModelVersionOut.model_validate(version) for version in versions]


@router.post("", response_model=ModelVersionOut, status_code=status.HTTP_201_CREATED)
async def register_model(
    payload: ModelVersionRegisterRequest,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> ModelVersionOut:
    """Registers a new weights version and always triggers the golden-set evaluation (FR-12) —
    the payload has no `metrics` field, so there is no way to set them except that evaluation
    actually running (RN-10).
    """
    model_version = await models_service.register_model_version(
        db, version=payload.version, weights_path=payload.weights_path
    )
    # Enqueued after commit (mirrors app.ingestion.service's enqueue-after-commit pattern,
    # section 3.5) and offloaded to a thread so the blocking Redis call never stalls the
    # event loop.
    await asyncio.to_thread(run_model_evaluation.delay, str(model_version.id))
    return ModelVersionOut.model_validate(model_version)


@router.get("/{model_version_id}/evaluation", response_model=ModelEvaluationOut)
async def get_model_evaluation(
    model_version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> ModelEvaluationOut:
    model_version = await models_service.get_model_version(db, model_version_id)
    return ModelEvaluationOut(
        id=model_version.id,
        version=model_version.version,
        evaluation_status=model_version.evaluation_status,
        metrics=model_version.metrics,
        evaluation_error=model_version.evaluation_error,
    )


@router.post("/{model_version_id}/activate", response_model=ModelVersionOut)
async def activate_model(
    model_version_id: uuid.UUID,
    payload: ModelVersionActivateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ModelVersionOut:
    """Activation gate (FR-12, NFR-05): rejected while evaluation is pending, rejected below
    the mAP@50 floor unless explicitly, auditably overridden. On success, reloads the
    inference worker without dropping in-flight requests (`app.tasks.models`).
    """
    model_version = await models_service.activate_model_version(
        db,
        actor_id=current_user.id,
        model_version_id=model_version_id,
        override=payload.override,
        justification=payload.justification,
    )
    await asyncio.to_thread(reload_inference_model.delay)
    return ModelVersionOut.model_validate(model_version)
