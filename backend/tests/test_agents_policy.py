"""Agent analysis trigger policy tests (FR-06's `agent_analysis_mode`, issue #31): the three
`conditional` conditions, `always`, `on_demand`, and reading the policy from `SystemConfig`
(issue #30) with sensible defaults when unset.
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.policy import AgentAnalysisPolicyConfig, evaluate_trigger, load_policy_config
from app.models import Detection, SystemConfig
from app.models.enums import DefectType, Severity


def _detection(defect_type: DefectType) -> Detection:
    return Detection(
        id=uuid.uuid4(),
        image_id=uuid.uuid4(),
        defect_type=defect_type,
        bbox={"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4},
        confidence=Decimal("0.900"),
        is_reported=True,
        model_version_id=uuid.uuid4(),
    )


def _config(**overrides: object) -> AgentAnalysisPolicyConfig:
    base: dict[str, object] = {
        "mode": "conditional",
        "min_defect_count": 3,
        "critical_classes": frozenset({DefectType.SHORT}),
        "min_severity": Severity.HIGH,
        "max_review_attempts": 2,
    }
    base.update(overrides)
    return AgentAnalysisPolicyConfig(**base)  # type: ignore[arg-type]


# --- conditional mode: N+ reportable defects --------------------------------------------------


def test_conditional_triggers_when_defect_count_meets_threshold() -> None:
    config = _config(
        min_defect_count=3, critical_classes=frozenset(), min_severity=Severity.CRITICAL
    )
    detections = [_detection(DefectType.SPUR) for _ in range(3)]

    triggered, reason = evaluate_trigger(config, detections, Severity.LOW)

    assert triggered is True
    assert "reportable_defect_count" in reason


def test_conditional_does_not_trigger_below_defect_count_threshold() -> None:
    config = _config(
        min_defect_count=3, critical_classes=frozenset(), min_severity=Severity.CRITICAL
    )
    detections = [_detection(DefectType.SPUR) for _ in range(2)]

    triggered, _ = evaluate_trigger(config, detections, Severity.LOW)

    assert triggered is False


# --- conditional mode: a configurable critical class is present --------------------------------


def test_conditional_triggers_when_a_critical_class_is_present() -> None:
    config = _config(
        min_defect_count=10,
        critical_classes=frozenset({DefectType.SHORT}),
        min_severity=Severity.CRITICAL,
    )
    detections = [_detection(DefectType.SHORT)]

    triggered, reason = evaluate_trigger(config, detections, Severity.LOW)

    assert triggered is True
    assert "critical_class_present" in reason


def test_conditional_does_not_trigger_without_a_critical_class() -> None:
    config = _config(
        min_defect_count=10,
        critical_classes=frozenset({DefectType.SHORT}),
        min_severity=Severity.CRITICAL,
    )
    detections = [_detection(DefectType.SPUR)]

    triggered, _ = evaluate_trigger(config, detections, Severity.LOW)

    assert triggered is False


# --- conditional mode: baseline severity >= high ------------------------------------------------


def test_conditional_triggers_when_baseline_severity_at_or_above_min() -> None:
    config = _config(min_defect_count=10, critical_classes=frozenset(), min_severity=Severity.HIGH)
    detections = [_detection(DefectType.MISSING_HOLE)]

    triggered, reason = evaluate_trigger(config, detections, Severity.HIGH)

    assert triggered is True
    assert "baseline_severity_max" in reason


def test_conditional_does_not_trigger_below_min_severity() -> None:
    config = _config(min_defect_count=10, critical_classes=frozenset(), min_severity=Severity.HIGH)
    detections = [_detection(DefectType.MOUSE_BITE)]

    triggered, reason = evaluate_trigger(config, detections, Severity.MEDIUM)

    assert triggered is False
    assert reason == "conditional: no trigger condition met"


# --- always / on_demand modes -------------------------------------------------------------------


def test_always_mode_triggers_regardless_of_criteria() -> None:
    config = _config(
        mode="always",
        min_defect_count=999,
        critical_classes=frozenset(),
        min_severity=Severity.CRITICAL,
    )
    detections = [_detection(DefectType.SPUR)]

    triggered, reason = evaluate_trigger(config, detections, Severity.LOW)

    assert triggered is True
    assert reason == "agent_analysis_mode=always"


def test_on_demand_mode_never_triggers_automatically() -> None:
    config = _config(mode="on_demand")
    detections = [_detection(DefectType.SHORT) for _ in range(5)]

    triggered, reason = evaluate_trigger(config, detections, Severity.CRITICAL)

    assert triggered is False
    assert "on_demand" in reason


# --- load_policy_config: defaults + reading SystemConfig (issue #30) ---------------------------


async def test_load_policy_config_defaults_when_unset(db_session: AsyncSession) -> None:
    """Mirrors `app/db/seed.py`'s `DEFAULT_SYSTEM_CONFIG` — a fresh DB with no seeded config
    (or a dev environment before `python -m app.db.seed` runs) must still behave predictably.
    """
    config = await load_policy_config(db_session)

    assert config.mode == "conditional"
    assert config.min_defect_count == 3
    assert config.critical_classes == frozenset({DefectType.SHORT})
    assert config.min_severity == Severity.HIGH
    assert config.max_review_attempts == 2


async def test_load_policy_config_reads_configured_values(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            SystemConfig(key="agent_analysis_mode", value="always"),
            SystemConfig(key="agent_analysis_min_defect_count", value=5),
            SystemConfig(key="agent_analysis_critical_classes", value=["open_circuit", "short"]),
            SystemConfig(key="agent_analysis_min_severity", value="critical"),
            SystemConfig(key="agent_analysis_max_review_attempts", value=4),
        ]
    )
    await db_session.commit()

    config = await load_policy_config(db_session)

    assert config.mode == "always"
    assert config.min_defect_count == 5
    assert config.critical_classes == frozenset({DefectType.OPEN_CIRCUIT, DefectType.SHORT})
    assert config.min_severity == Severity.CRITICAL
    assert config.max_review_attempts == 4
