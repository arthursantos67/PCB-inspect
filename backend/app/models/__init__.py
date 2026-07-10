"""Importing this package registers every mapped model on `Base.metadata` (Alembic autogenerate)."""

from app.models.analysis import Analysis
from app.models.audit_log import AuditLog
from app.models.batch import Batch
from app.models.board import Board
from app.models.detection import Detection
from app.models.inspection_image import InspectionImage
from app.models.model_version import ModelVersion
from app.models.system_config import SystemConfig
from app.models.user import User

__all__ = [
    "Analysis",
    "AuditLog",
    "Batch",
    "Board",
    "Detection",
    "InspectionImage",
    "ModelVersion",
    "SystemConfig",
    "User",
]
