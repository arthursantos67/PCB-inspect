"""Reading a stored analysis in a language it was not written in (issue #50).

`app.analyses.localization` has to answer in the station's language without ever failing its
caller, and without paying an LLM more than once per analysis per language. The routes it can
take differ in cost, so each one is pinned here: a baseline analysis is rebuilt from the
curated catalogue for free, an agent analysis is translated once and then read from the cache,
a translation the model got structurally wrong is discarded whole, and the interactive path
(`allow_llm=False`) never reaches the model at all.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_client import LLMUnavailableError
from app.analyses.localization import (
    analysis_language,
    localize_analyses,
    localize_analysis,
)
from app.core.language import DEFAULT_LANGUAGE, Language, coerce_language
from app.knowledge.defects import knowledge_base
from app.models import Analysis, Detection, InspectionImage, ModelVersion
from app.models.enums import (
    AnalysisSource,
    AnalysisStatus,
    DefectType,
    DispositionRecommendation,
    ImageSource,
    ImageStatus,
    Severity,
)


class _StubLLM:
    """Stands in for `app.agents.llm_client.LLMClient` (a Protocol, so duck typing is how it is
    substituted). `payload=None` means the model is unreachable.
    """

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        self.calls.append((system, user))
        if self.payload is None:
            raise LLMUnavailableError("no analysis model configured")
        return self.payload


async def _seed_board(
    db: AsyncSession, *, defect_type: DefectType = DefectType.SHORT
) -> tuple[InspectionImage, Detection]:
    # Left inactive: a test can seed several boards, and RN-02 allows only one active version.
    model_version = ModelVersion(
        version=f"v-{uuid.uuid4().hex[:8]}", weights_path="/weights/best.pt"
    )
    image = InspectionImage(
        source=ImageSource.WATCH_FOLDER,
        original_path=f"/tmp/{uuid.uuid4()}.jpg",
        checksum_sha256=uuid.uuid4().hex,
        status=ImageStatus.COMPLETED,
    )
    db.add_all([model_version, image])
    await db.flush()

    detection = Detection(
        image_id=image.id,
        defect_type=defect_type,
        bbox={"x1": 0.1, "y1": 0.1, "x2": 0.3, "y2": 0.3},
        confidence=Decimal("0.910"),
        is_reported=True,
        model_version_id=model_version.id,
    )
    db.add(detection)
    await db.flush()
    return image, detection


def _analysis(
    image: InspectionImage,
    detection: Detection,
    *,
    source: AnalysisSource,
    language: str | None = "en",
    severity: Severity = Severity.HIGH,
    translations: dict[str, Any] | None = None,
) -> Analysis:
    return Analysis(
        image_id=image.id,
        status=AnalysisStatus.COMPLETED,
        source=source,
        language=language,
        translations=translations,
        per_defect=[
            {
                "detection_id": str(detection.id),
                "defect_type": detection.defect_type.value,
                "severity": severity.value,
                "description": "Solder bridges two adjacent pads.",
                "probable_causes": ["Excess solder paste"],
                "suggested_solutions": ["Rework the joint under a microscope"],
            }
        ],
        executive_summary="This board needs rework.",
        disposition_recommendation=DispositionRecommendation.REWORK,
        severity_max=severity,
    )


async def test_language_of_a_row_written_before_the_setting_existed_reads_as_english() -> None:
    assert coerce_language(None) is DEFAULT_LANGUAGE
    assert coerce_language("fr") is DEFAULT_LANGUAGE
    assert coerce_language(" PT ") is Language.PT
    assert coerce_language(Language.PT) is Language.PT


async def test_analysis_already_in_the_asked_for_language_is_returned_untouched(
    db_session: AsyncSession,
) -> None:
    image, detection = await _seed_board(db_session)
    analysis = _analysis(image, detection, source=AnalysisSource.AGENTS, language="en")
    db_session.add(analysis)
    await db_session.commit()

    client = _StubLLM()
    localized = await localize_analysis(db_session, analysis, language=Language.EN, client=client)

    assert localized is not None
    assert localized.language is Language.EN
    assert localized.per_defect[0]["description"] == "Solder bridges two adjacent pads."
    assert client.calls == []


async def test_baseline_analysis_is_rebuilt_from_the_catalogue_without_the_model(
    db_session: AsyncSession,
) -> None:
    """The baseline's prose *is* the catalogue, which exists in both languages, so the other
    language is a dict lookup rather than an LLM call.
    """
    image, detection = await _seed_board(db_session)
    analysis = _analysis(image, detection, source=AnalysisSource.KNOWLEDGE_BASE, language="en")
    db_session.add(analysis)
    await db_session.commit()

    client = _StubLLM()
    localized = await localize_analysis(db_session, analysis, language=Language.PT, client=client)

    expected = knowledge_base(Language.PT)[DefectType.SHORT]
    assert localized is not None
    assert localized.language is Language.PT
    assert localized.per_defect[0]["description"] == expected.description
    assert localized.per_defect[0]["probable_causes"] == list(expected.probable_causes)
    assert client.calls == []


async def test_baseline_is_read_from_the_catalogue_even_in_its_own_language(
    db_session: AsyncSession,
) -> None:
    """The stored row only holds the copy of the catalogue that was current the day the board
    was inspected. Reading it from the catalogue every time is what lets a correction to the
    wording reach boards already in the database, which is how boards inspected before the
    defect class names stopped being translated read correctly without a data migration.
    """
    image, detection = await _seed_board(db_session)
    analysis = _analysis(image, detection, source=AnalysisSource.KNOWLEDGE_BASE, language="pt")
    db_session.add(analysis)
    await db_session.commit()

    client = _StubLLM()
    localized = await localize_analysis(db_session, analysis, language=Language.PT, client=client)

    expected = knowledge_base(Language.PT)[DefectType.SHORT]
    assert localized is not None
    # Not the row's own "Solder bridges two adjacent pads.", which is the stale copy.
    assert localized.per_defect[0]["description"] == expected.description
    assert client.calls == []


async def test_baseline_rebuild_keeps_the_severity_a_reviewer_corrected(
    db_session: AsyncSession,
) -> None:
    """`short` is critical in the catalogue; the stored entry says low because someone on the
    floor said so (FR-10). Reading the board in Portuguese must not undo that.
    """
    image, detection = await _seed_board(db_session)
    analysis = _analysis(
        image, detection, source=AnalysisSource.KNOWLEDGE_BASE, severity=Severity.LOW
    )
    db_session.add(analysis)
    await db_session.commit()

    localized = await localize_analysis(db_session, analysis, language=Language.PT)

    assert localized is not None
    assert localized.per_defect[0]["severity"] == Severity.LOW.value
    assert knowledge_base(Language.PT)[DefectType.SHORT].severity is not Severity.LOW


async def test_agent_analysis_is_translated_once_and_then_read_from_the_cache(
    db_session: AsyncSession,
) -> None:
    image, detection = await _seed_board(db_session)
    analysis = _analysis(image, detection, source=AnalysisSource.AGENTS)
    db_session.add(analysis)
    await db_session.commit()

    client = _StubLLM(
        {
            "findings": [
                {
                    "detection_id": str(detection.id),
                    "description": "Solda formando ponte entre duas ilhas vizinhas.",
                    "probable_causes": ["Excesso de pasta de solda"],
                    "suggested_solutions": ["Retrabalhar a junta sob o microscópio"],
                }
            ],
            "executive_summary": "Esta placa precisa de retrabalho.",
        }
    )
    localized = await localize_analysis(db_session, analysis, language=Language.PT, client=client)

    assert localized is not None
    assert localized.language is Language.PT
    assert localized.per_defect[0]["description"].startswith("Solda formando ponte")
    assert localized.executive_summary == "Esta placa precisa de retrabalho."
    # Structure comes from the stored analysis, never from the model.
    assert localized.per_defect[0]["detection_id"] == str(detection.id)
    assert localized.per_defect[0]["severity"] == Severity.HIGH.value
    assert len(client.calls) == 1

    # Cached on the row, so the second reader pays nothing.
    await db_session.refresh(analysis)
    assert analysis.translations is not None
    assert analysis.translations["pt"]["per_defect"][0]["description"].startswith("Solda formando")
    assert analysis_language(analysis) is Language.EN

    again = await localize_analysis(db_session, analysis, language=Language.PT, client=client)
    assert again is not None
    assert again.per_defect[0]["description"].startswith("Solda formando ponte")
    assert len(client.calls) == 1


async def test_structurally_wrong_translation_is_discarded_whole(
    db_session: AsyncSession,
) -> None:
    """A model that renamed the detection_id would attach its text to the wrong defect, so the
    stored English is kept and nothing is cached.
    """
    image, detection = await _seed_board(db_session)
    analysis = _analysis(image, detection, source=AnalysisSource.AGENTS)
    db_session.add(analysis)
    await db_session.commit()

    client = _StubLLM(
        {
            "findings": [
                {
                    "detection_id": str(uuid.uuid4()),
                    "description": "Texto de outra placa.",
                    "probable_causes": ["Causa"],
                    "suggested_solutions": ["Solução"],
                }
            ],
            "executive_summary": "Resumo.",
        }
    )
    localized = await localize_analysis(db_session, analysis, language=Language.PT, client=client)

    assert localized is not None
    assert localized.language is Language.EN
    assert localized.per_defect[0]["description"] == "Solder bridges two adjacent pads."
    await db_session.refresh(analysis)
    assert not (analysis.translations or {})


async def test_unreachable_model_leaves_the_analysis_in_its_original_language(
    db_session: AsyncSession,
) -> None:
    image, detection = await _seed_board(db_session)
    analysis = _analysis(image, detection, source=AnalysisSource.AGENTS)
    db_session.add(analysis)
    await db_session.commit()

    localized = await localize_analysis(
        db_session, analysis, language=Language.PT, client=_StubLLM(payload=None)
    )

    assert localized is not None
    assert localized.language is Language.EN
    assert localized.per_defect[0]["description"] == "Solder bridges two adjacent pads."


async def test_interactive_path_never_calls_the_model(db_session: AsyncSession) -> None:
    """The analysis detail screen asks with `allow_llm=False`: a page load cannot hang for the
    minutes a local CPU model takes, so an untranslated board comes back as written.
    """
    image, detection = await _seed_board(db_session)
    analysis = _analysis(image, detection, source=AnalysisSource.AGENTS)
    db_session.add(analysis)
    await db_session.commit()

    client = _StubLLM({"findings": [], "executive_summary": None})
    localized = await localize_analysis(
        db_session, analysis, language=Language.PT, client=client, allow_llm=False
    )

    assert localized is not None
    assert localized.language is Language.EN
    assert client.calls == []


async def test_interactive_path_still_reads_a_cached_translation(
    db_session: AsyncSession,
) -> None:
    image, detection = await _seed_board(db_session)
    analysis = _analysis(
        image,
        detection,
        source=AnalysisSource.AGENTS,
        translations={
            "pt": {
                "per_defect": [
                    {
                        "detection_id": str(detection.id),
                        "severity": Severity.HIGH.value,
                        "description": "Solda formando ponte entre duas ilhas vizinhas.",
                        "probable_causes": ["Excesso de pasta de solda"],
                        "suggested_solutions": ["Retrabalhar a junta"],
                    }
                ],
                "executive_summary": "Esta placa precisa de retrabalho.",
            }
        },
    )
    db_session.add(analysis)
    await db_session.commit()

    localized = await localize_analysis(db_session, analysis, language=Language.PT, allow_llm=False)

    assert localized is not None
    assert localized.language is Language.PT
    assert localized.executive_summary == "Esta placa precisa de retrabalho."


async def test_a_report_over_baseline_boards_never_builds_an_llm_client(
    db_session: AsyncSession, monkeypatch
) -> None:
    """`localize_analyses` builds the client once, and only when something actually needs the
    model, so a Portuguese report over baseline-only boards stays offline.
    """
    built = 0

    async def _build_llm_client(_db: AsyncSession):
        nonlocal built
        built += 1
        return _StubLLM()

    monkeypatch.setattr(
        "app.analyses.localization.build_llm_client", _build_llm_client, raising=True
    )

    analyses = []
    for defect_type in (DefectType.SHORT, DefectType.SPUR):
        image, detection = await _seed_board(db_session, defect_type=defect_type)
        analysis = _analysis(image, detection, source=AnalysisSource.KNOWLEDGE_BASE)
        db_session.add(analysis)
        analyses.append(analysis)
    await db_session.commit()

    localized = await localize_analyses(db_session, analyses, language=Language.PT)

    assert built == 0
    assert len(localized) == 2
    assert all(item.language is Language.PT for item in localized.values())
