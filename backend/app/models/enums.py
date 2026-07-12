import enum

from sqlalchemy import Enum as SAEnum


def pg_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """A CHECK-constraint-backed enum column (native_enum=False) storing `.value`, not `.name`.

    Kept as VARCHAR + CHECK rather than a native Postgres ENUM type so that adding a new
    member later is a plain constraint migration, not an ALTER TYPE.
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        validate_strings=True,
        values_callable=lambda obj: [e.value for e in obj],
    )


class ImageSource(enum.StrEnum):
    WATCH_FOLDER = "watch_folder"
    DIRECTORY_SCAN = "directory_scan"
    MANUAL_IMPORT = "manual_import"


class ImageStatus(enum.StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    DETECTED = "DETECTED"
    ANALYZING = "ANALYZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DefectType(enum.StrEnum):
    MISSING_HOLE = "missing_hole"
    MOUSE_BITE = "mouse_bite"
    OPEN_CIRCUIT = "open_circuit"
    SHORT = "short"
    SPUR = "spur"
    SPURIOUS_COPPER = "spurious_copper"


class DetectionReview(enum.StrEnum):
    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"
    FALSE_POSITIVE = "false_positive"


class AnalysisStatus(enum.StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


class AnalysisSource(enum.StrEnum):
    KNOWLEDGE_BASE = "knowledge_base"
    AGENTS = "agents"


class DispositionRecommendation(enum.StrEnum):
    APPROVE = "approve"
    REWORK = "rework"
    DISCARD = "discard"


class Severity(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AnalysisReviewStatus(enum.StrEnum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class ChatRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}


def severity_rank(severity: Severity) -> int:
    """Total order over `Severity` (low < medium < high < critical) — shared by every place
    that needs to compare or max() severities: baseline analysis (`app.analyses.service`),
    the agent chain's conditional trigger policy (`app.agents.policy`), and the Summarizer's
    output.
    """
    return _SEVERITY_RANK[severity]
