"""Importing this package registers every mapped model on `Base.metadata` (Alembic autogenerate)."""

from app.models.analysis import Analysis
from app.models.analysis_review import AnalysisReview
from app.models.audit_log import AuditLog
from app.models.batch import Batch
from app.models.board import Board
from app.models.board_disposition import BoardDisposition
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.dataset_export import DatasetExport
from app.models.detection import Detection
from app.models.inspection_image import InspectionImage
from app.models.model_version import ModelVersion
from app.models.quality_alert import QualityAlert
from app.models.report import Report
from app.models.system_config import SystemConfig
from app.models.user import User

__all__ = [
    "Analysis",
    "AnalysisReview",
    "AuditLog",
    "Batch",
    "Board",
    "BoardDisposition",
    "ChatMessage",
    "ChatSession",
    "DatasetExport",
    "Detection",
    "InspectionImage",
    "ModelVersion",
    "QualityAlert",
    "Report",
    "SystemConfig",
    "User",
]
