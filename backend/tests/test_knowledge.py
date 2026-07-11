"""Defect knowledge base coverage (FR-06's baseline tier, Issue 7): every fixed defect
class must have curated, non-empty content so the baseline analysis can never fall back to
placeholder text.
"""

from app.knowledge.defects import DEFECT_KNOWLEDGE_BASE
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
