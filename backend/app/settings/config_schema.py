"""Per-key validation registry for dynamic system configuration (FR-13, issue #30).

`update_config` runs every incoming key through `validate_config_value` before anything is
written, so a batch `PATCH` with one bad key rejects atomically instead of partially applying.
Reuses the same enums as the ORM models (`DefectType`, `Severity`) so the allowed values here
can never drift from what the rest of the system actually accepts.
"""

from collections.abc import Callable
from typing import Any

from app.core.errors import ApiError
from app.models.enums import DefectType, Severity


def _range(key: str, value: Any, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ApiError("CONFIG_INVALID_VALUE", f"{key} must be a number", 422) from None
    if not (low <= number <= high):
        raise ApiError(
            "CONFIG_INVALID_VALUE", f"{key} must be between {low} and {high}", 422
        )
    return number


def _positive_int(key: str, value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ApiError("CONFIG_INVALID_VALUE", f"{key} must be an integer", 422) from None
    if number <= 0:
        raise ApiError("CONFIG_INVALID_VALUE", f"{key} must be a positive integer", 422)
    return number


def _positive_number(key: str, value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ApiError("CONFIG_INVALID_VALUE", f"{key} must be a number", 422) from None
    if number <= 0:
        raise ApiError("CONFIG_INVALID_VALUE", f"{key} must be a positive number", 422)
    return number


def _bool(key: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ApiError("CONFIG_INVALID_VALUE", f"{key} must be true or false", 422)
    return value


def _enum(key: str, value: Any, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ApiError(
            "CONFIG_INVALID_VALUE", f"{key} must be one of: {', '.join(allowed)}", 422
        )
    return str(value)


def _non_empty_str(key: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApiError("CONFIG_INVALID_VALUE", f"{key} must be a non-empty string", 422)
    return value


def _secret_str(key: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ApiError("CONFIG_INVALID_VALUE", f"{key} must be a string", 422)
    return value


def _defect_type_list(key: str, value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ApiError(
            "CONFIG_INVALID_VALUE", f"{key} must be a list of defect types", 422
        )
    allowed = {member.value for member in DefectType}
    invalid = [str(item) for item in value if item not in allowed]
    if invalid:
        raise ApiError(
            "CONFIG_INVALID_VALUE",
            f"{key} contains unknown defect type(s): {', '.join(invalid)}",
            422,
        )
    return value


_SEVERITY_VALUES = tuple(member.value for member in Severity)

# Every value FR-13 requires the operator to be able to read/write, plus the ingestion keys
# already in use since issue #4 — no key outside this set is accepted by `update_config`.
_VALIDATORS: dict[str, Callable[[str, Any], Any]] = {
    # Confidence thresholds (RV-03)
    "min_confidence_store": lambda k, v: _range(k, v, 0, 1),
    "min_confidence_report": lambda k, v: _range(k, v, 0, 1),
    # LLM connection (section 5.2)
    "llm.provider": lambda k, v: _enum(k, v, ("openai_compatible", "anthropic", "google")),
    "llm.base_url": _non_empty_str,
    "llm.model": _non_empty_str,
    "llm.api_key": _secret_str,
    "llm.timeout_s": _positive_int,
    # Agent analysis policy and trigger criteria (FR-06)
    "agent_analysis_mode": lambda k, v: _enum(k, v, ("conditional", "always", "on_demand")),
    "agent_analysis_min_defect_count": _positive_int,
    "agent_analysis_critical_classes": _defect_type_list,
    "agent_analysis_min_severity": lambda k, v: _enum(k, v, _SEVERITY_VALUES),
    # Quality alert thresholds (FR-19)
    "alert_defect_rate_threshold": lambda k, v: _range(k, v, 0, 1),
    "alert_window_minutes": _positive_int,
    # Watch root path and naming convention (FR-03)
    "watch_root_path": _non_empty_str,
    "watch_naming_convention": lambda k, v: _enum(
        k, v, ("subdirectory_batch_filename_board",)
    ),
    "watch_mode_enabled": _bool,
    "import_max_size_mb": _positive_number,
    # Retention (FR-17) and reports/exports output directory (FR-11/FR-18)
    "retention_days": _positive_int,
    "reports_output_dir": _non_empty_str,
}


def validate_config_value(key: str, value: Any) -> Any:
    """Returns the normalized value, or raises `ApiError` (422).

    `None`/`""` always pass through unvalidated — that's the existing "clear this key" signal
    (e.g. resetting `llm.api_key`, per issue #21), and it must keep working for every key, not
    just secrets.
    """
    if value in (None, ""):
        return value
    validator = _VALIDATORS.get(key)
    if validator is None:
        raise ApiError("CONFIG_UNKNOWN_KEY", f"Unknown configuration key: {key}", 422)
    return validator(key, value)
