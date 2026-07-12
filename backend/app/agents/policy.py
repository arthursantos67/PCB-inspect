"""Agent analysis trigger policy (FR-06's `agent_analysis_mode`, issue #31).

Evaluated once per image, right after the baseline analysis (issue #7) is computed but before
the image leaves `DETECTED` — `conditional` mode's three documented conditions are checked
against the exact `reportable_detections`/severity the baseline just used, so this never
re-queries detections or duplicates a knowledge-base lookup (`app.analyses.service`).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Detection
from app.models.enums import DefectType, Severity, severity_rank
from app.settings.service import get_config_value

# Mirrors `app/db/seed.py`'s `DEFAULT_SYSTEM_CONFIG` so behavior is identical whether or not
# these keys have actually been seeded into `SystemConfig` yet (e.g. in tests that don't seed).
DEFAULT_MODE = "conditional"
DEFAULT_MIN_DEFECT_COUNT = 3
DEFAULT_CRITICAL_CLASSES: frozenset[DefectType] = frozenset({DefectType.SHORT})
DEFAULT_MIN_SEVERITY = Severity.HIGH
DEFAULT_MAX_REVIEW_ATTEMPTS = 2


@dataclass(frozen=True)
class AgentAnalysisPolicyConfig:
    mode: str  # "conditional" | "always" | "on_demand" (validated at the config layer, issue #30)
    min_defect_count: int
    critical_classes: frozenset[DefectType]
    min_severity: Severity
    max_review_attempts: int


async def load_policy_config(db: AsyncSession) -> AgentAnalysisPolicyConfig:
    mode = await get_config_value(db, "agent_analysis_mode", DEFAULT_MODE)
    min_defect_count = await get_config_value(
        db, "agent_analysis_min_defect_count", DEFAULT_MIN_DEFECT_COUNT
    )
    critical_classes_raw = await get_config_value(
        db, "agent_analysis_critical_classes", [c.value for c in DEFAULT_CRITICAL_CLASSES]
    )
    min_severity_raw = await get_config_value(
        db, "agent_analysis_min_severity", DEFAULT_MIN_SEVERITY.value
    )
    max_review_attempts = await get_config_value(
        db, "agent_analysis_max_review_attempts", DEFAULT_MAX_REVIEW_ATTEMPTS
    )
    return AgentAnalysisPolicyConfig(
        mode=str(mode),
        min_defect_count=int(min_defect_count),
        critical_classes=frozenset(DefectType(v) for v in critical_classes_raw),
        min_severity=Severity(min_severity_raw),
        max_review_attempts=int(max_review_attempts),
    )


def evaluate_trigger(
    config: AgentAnalysisPolicyConfig,
    reportable_detections: Sequence[Detection],
    severity_max: Severity,
) -> tuple[bool, str]:
    """Returns `(should_run, reason)` — `reason` is always populated (even when `False`) so
    the caller can log why the agent tier did or didn't run (`app.tasks.pipeline`).

    Only ever called with a non-empty `reportable_detections` (the caller's no-defect path
    never reaches here) — `always` therefore means "every image with >=1 reportable
    detection," matching issue #31's "always triggers on every reportable detection."
    """
    if config.mode == "always":
        return True, "agent_analysis_mode=always"
    if config.mode == "on_demand":
        return False, "agent_analysis_mode=on_demand (automatic trigger disabled)"
    if config.mode != "conditional":
        # Unreachable in practice — validated at the config layer (issue #30) — but never
        # silently auto-trigger on an unrecognized mode value.
        return False, f"unrecognized agent_analysis_mode={config.mode!r}"

    count = len(reportable_detections)
    if count >= config.min_defect_count:
        return (
            True,
            f"reportable_defect_count={count} >= min_defect_count={config.min_defect_count}",
        )

    present_critical = {d.defect_type for d in reportable_detections} & config.critical_classes
    if present_critical:
        classes = ", ".join(sorted(c.value for c in present_critical))
        return True, f"critical_class_present=[{classes}]"

    if severity_rank(severity_max) >= severity_rank(config.min_severity):
        return (
            True,
            f"baseline_severity_max={severity_max.value} "
            f">= min_severity={config.min_severity.value}",
        )

    return False, "conditional: no trigger condition met"
