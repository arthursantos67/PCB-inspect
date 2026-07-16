import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ModelEvaluationStatus


class ModelVersionRegisterRequest(BaseModel):
    version: str = Field(min_length=1)
    weights_path: str = Field(min_length=1)


class ModelVersionActivateRequest(BaseModel):
    # `override`/`justification` are the explicit, audited escape hatch for a version below
    # the mAP@50 floor (NFR-05) — never accepted implicitly.
    override: bool = False
    justification: str | None = None


class ModelVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: str
    weights_path: str
    metrics: dict[str, Any] | None
    evaluation_status: ModelEvaluationStatus
    evaluation_error: str | None
    is_active: bool
    activated_at: datetime | None
    created_at: datetime


class ModelEvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: str
    evaluation_status: ModelEvaluationStatus
    metrics: dict[str, Any] | None
    evaluation_error: str | None
