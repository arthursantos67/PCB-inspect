"""Defect knowledge base coverage (FR-06's baseline tier, Issue 7): every fixed defect
class must have curated, non-empty content so the baseline analysis can never fall back to
placeholder text.
"""

from app.knowledge.defects import DEFECT_KNOWLEDGE_BASE, severity_from_defect_counts
from app.models.enums import DefectType, Severity


def test_knowledge_base_covers_every_defect_class() -> None:
    assert set(DEFECT_KNOWLEDGE_BASE.keys()) == set(DefectType)


def test_every_entry_has_non_empty_curated_content() -> None:
    for defect_type, entry in DEFECT_KNOWLEDGE_BASE.items():
        assert entry.description.strip(), defect_type
        assert len(entry.probable_causes) > 0, defect_type
        assert all(cause.strip() for cause in entry.probable_causes), defect_type
        assert len(entry.suggested_solutions) > 0, defect_type
        assert all(sol.strip() for sol in entry.suggested_solutions), defect_type
        assert isinstance(entry.severity, Severity), defect_type


# --- Aggregated severity ----------------------------------------------------------------------


def test_severity_is_none_without_defects() -> None:
    assert severity_from_defect_counts({}, defect_rate=0.0) is None


def test_composition_decides_severity_at_the_same_spread() -> None:
    """Same defect count, same share of defective boards: the defect *classes* separate them."""
    nuisance = severity_from_defect_counts({DefectType.MOUSE_BITE: 4}, defect_rate=1.0)
    critical = severity_from_defect_counts({DefectType.OPEN_CIRCUIT: 4}, defect_rate=1.0)

    assert nuisance is Severity.LOW
    assert critical is Severity.CRITICAL


def test_how_widespread_the_defect_is_changes_the_reading() -> None:
    """The actual requirement: the share of defective boards in the batch has to matter.
    Two critical boards out of 500 must not read like 400 out of 500.
    """
    counts = {DefectType.OPEN_CIRCUIT: 2}

    assert severity_from_defect_counts(counts, defect_rate=2 / 500) is Severity.MEDIUM
    assert severity_from_defect_counts(counts, defect_rate=400 / 500) is Severity.CRITICAL


def test_a_rare_critical_defect_never_reads_as_low() -> None:
    """The rate scales the reading down, it never erases the class: an open circuit found on
    one board out of thousands is still a critical finding on that board.
    """
    assert (
        severity_from_defect_counts({DefectType.OPEN_CIRCUIT: 1}, defect_rate=0.0)
        is Severity.MEDIUM
    )


def test_defect_rate_outside_zero_to_one_is_clamped() -> None:
    counts = {DefectType.SPURIOUS_COPPER: 3}

    assert severity_from_defect_counts(counts, defect_rate=5.0) is severity_from_defect_counts(
        counts, defect_rate=1.0
    )
    assert severity_from_defect_counts(counts, defect_rate=-1.0) is severity_from_defect_counts(
        counts, defect_rate=0.0
    )
