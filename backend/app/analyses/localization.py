"""A stored analysis rendered in a language other than the one it was written in (issue #50).

Reports and the analysis screen both hit the same problem: `Analysis.per_defect` and
`Analysis.executive_summary` hold prose written when the analysis ran, in whatever language
the station was set to then. Switching the station to Portuguese cannot retroactively rewrite
what a model already wrote, and re-running the chain is not an option (a board costs minutes
of CPU inference, and the text has already been validated on screen by a reviewer).

So the text is localized on read, by whichever route is cheapest for the analysis at hand:

* **Baseline analyses are rebuilt, not translated.** Their prose *is* the curated catalogue
  (`app.knowledge.defects`), which exists in both languages, so the other language's version
  is a dict lookup: exact, instant, and free. This covers every analysis on a station with no
  LLM configured at all.
* **Agent analyses are translated once and cached** on `Analysis.translations`, keyed by
  language. The first report (or screen) asking for the other language pays for one LLM call
  per board; every one after that reads the cache.

Nothing here is allowed to fail a caller. A report that renders a board's analysis in the
original language is still a correct, usable report; a report that raises is a FAILED row an
operator can do nothing about. Every failure path therefore returns the stored text.
"""

import json
import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.agents.llm_client import LLMClient, LLMUnavailableError, build_llm_client
from app.core.language import DEFAULT_LANGUAGE, Language, coerce_language
from app.knowledge.defects import knowledge_base
from app.models import Analysis, Detection
from app.models.enums import AnalysisSource

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LocalizedAnalysis:
    """An analysis' prose in the language that was asked for, plus the language it is actually
    in. The two differ when localization was not possible (no LLM reachable, model returned
    something unusable), which callers surface rather than hide: a Portuguese report that had
    to keep one board's English paragraph should say so, not pretend.
    """

    language: Language
    per_defect: list[dict[str, Any]]
    executive_summary: str | None

    @property
    def by_detection_id(self) -> dict[str, dict[str, Any]]:
        return {
            str(entry.get("detection_id")): entry
            for entry in self.per_defect
            if isinstance(entry, dict) and entry.get("detection_id")
        }


def analysis_language(analysis: Analysis) -> Language:
    """Which language an analysis' stored prose is in. Rows written before the setting existed
    have no value and were all written by English-only prompts.
    """
    return coerce_language(analysis.language, default=DEFAULT_LANGUAGE)


def _stored(analysis: Analysis) -> LocalizedAnalysis:
    return LocalizedAnalysis(
        language=analysis_language(analysis),
        per_defect=list(analysis.per_defect or []),
        executive_summary=analysis.executive_summary,
    )


# --- Baseline rebuild ----------------------------------------------------------------------


def _rebuild_baseline(
    analysis: Analysis, detections: Sequence[Detection], language: Language
) -> LocalizedAnalysis | None:
    """The baseline's per-defect entries regenerated from the target language's catalogue.

    Keeps the *stored* severity rather than the catalogue's: a reviewer may have corrected it
    on screen (FR-10), and translating a board must never quietly undo that.

    Returns `None` when the stored entries can't be matched to detections, which sends the
    caller down the translation path instead of inventing text for a board.
    """
    defect_type_by_id = {str(detection.id): detection.defect_type for detection in detections}
    catalog = knowledge_base(language)
    rebuilt: list[dict[str, Any]] = []
    for entry in analysis.per_defect or []:
        if not isinstance(entry, dict):
            return None
        detection_id = str(entry.get("detection_id"))
        defect_type = defect_type_by_id.get(detection_id)
        if defect_type is None:
            return None
        knowledge = catalog[defect_type]
        rebuilt.append(
            {
                "detection_id": detection_id,
                "description": knowledge.description,
                "probable_causes": list(knowledge.probable_causes),
                "suggested_solutions": list(knowledge.suggested_solutions),
                "severity": entry.get("severity") or knowledge.severity.value,
            }
        )
    return LocalizedAnalysis(
        language=language,
        per_defect=rebuilt,
        # A baseline analysis has no executive summary to speak of (only the agent chain
        # writes one), so there is nothing to carry over.
        executive_summary=analysis.executive_summary,
    )


# --- LLM translation -----------------------------------------------------------------------


class _TranslatedFinding(BaseModel):
    detection_id: str
    description: str
    probable_causes: list[str]
    suggested_solutions: list[str]


class _TranslationOutput(BaseModel):
    findings: list[_TranslatedFinding]
    executive_summary: str | None = None


_LANGUAGE_NAMES: dict[Language, str] = {
    Language.EN: "English",
    Language.PT: "Brazilian Portuguese",
}

# Deliberately a translator and nothing else. The temptation with an LLM in the loop is to let
# it "improve" the text on the way through, but this prose was validated by a reviewer in its
# original language (FR-10): the Portuguese an operator reads has to say the same thing the
# reviewer approved, not a second opinion about the board.
_SYSTEM_PROMPT = (
    "You translate PCB manufacturing inspection text. Translate every string given to you "
    "from {source} into {target}, using the vocabulary a PCB manufacturing engineer would "
    "use. Translate only: never add a finding, never drop one, never add commentary, never "
    "correct or improve what the text says, and keep every number, percentage, confidence "
    "value and defect class name exactly as given. The detection_id values are identifiers, "
    "not text: copy them back character for character. Keep each list the same length and in "
    "the same order. Never use em dashes or en dashes; use a comma, a colon, or a separate "
    "sentence. Respond with a single JSON object only, no prose and no markdown fences, "
    'shaped exactly: {{"findings": [{{"detection_id": str, "description": str, '
    '"probable_causes": [str], "suggested_solutions": [str]}}, ...], '
    '"executive_summary": str or null}}.'
)


def _translation_payload(source: LocalizedAnalysis) -> dict[str, Any]:
    return {
        "findings": [
            {
                "detection_id": str(entry.get("detection_id")),
                "description": str(entry.get("description") or ""),
                "probable_causes": [str(item) for item in entry.get("probable_causes") or []],
                "suggested_solutions": [
                    str(item) for item in entry.get("suggested_solutions") or []
                ],
            }
            for entry in source.per_defect
            if isinstance(entry, dict)
        ],
        "executive_summary": source.executive_summary,
    }


def _merge_translation(
    source: LocalizedAnalysis, output: _TranslationOutput, language: Language
) -> LocalizedAnalysis | None:
    """The model's strings folded back onto the original entries.

    Everything structural (`detection_id`, `severity`, the entry order) comes from the stored
    analysis, never from the model: the translation is only allowed to supply words. A model
    that dropped a finding, invented one, or renamed a detection_id has produced something
    that would misattribute text to the wrong defect, so the whole translation is discarded
    rather than partially applied.
    """
    translated = {finding.detection_id: finding for finding in output.findings}
    if len(translated) != len(output.findings):
        return None

    merged: list[dict[str, Any]] = []
    for entry in source.per_defect:
        if not isinstance(entry, dict):
            return None
        detection_id = str(entry.get("detection_id"))
        finding = translated.get(detection_id)
        if finding is None:
            return None
        if len(finding.probable_causes) != len(entry.get("probable_causes") or []):
            return None
        if len(finding.suggested_solutions) != len(entry.get("suggested_solutions") or []):
            return None
        merged.append(
            {
                **entry,
                "description": finding.description,
                "probable_causes": finding.probable_causes,
                "suggested_solutions": finding.suggested_solutions,
            }
        )

    summary = output.executive_summary if source.executive_summary else None
    return LocalizedAnalysis(language=language, per_defect=merged, executive_summary=summary)


def _cached(analysis: Analysis, language: Language) -> LocalizedAnalysis | None:
    cached = (analysis.translations or {}).get(language.value)
    if not isinstance(cached, dict) or not isinstance(cached.get("per_defect"), list):
        return None
    return LocalizedAnalysis(
        language=language,
        per_defect=cached["per_defect"],
        executive_summary=cached.get("executive_summary"),
    )


def _store_in_cache(analysis: Analysis, localized: LocalizedAnalysis) -> None:
    translations = dict(analysis.translations or {})
    translations[localized.language.value] = {
        "per_defect": localized.per_defect,
        "executive_summary": localized.executive_summary,
    }
    analysis.translations = translations
    # JSONB columns are replaced wholesale here, but flagging is cheap insurance against a
    # future in-place edit silently not being persisted.
    flag_modified(analysis, "translations")


async def _translate(
    source: LocalizedAnalysis, language: Language, client: LLMClient
) -> LocalizedAnalysis | None:
    system = _SYSTEM_PROMPT.format(
        source=_LANGUAGE_NAMES.get(source.language, source.language.value),
        target=_LANGUAGE_NAMES.get(language, language.value),
    )
    try:
        raw = await client.complete_json(
            system=system, user=json.dumps(_translation_payload(source), ensure_ascii=False)
        )
        output = _TranslationOutput.model_validate(raw)
    except (LLMUnavailableError, ValidationError, ValueError) as exc:
        logger.warning("Analysis translation to %s failed: %s", language.value, exc)
        return None
    return _merge_translation(source, output, language)


# --- Entry point ---------------------------------------------------------------------------


async def localize_analysis(
    db: AsyncSession,
    analysis: Analysis | None,
    *,
    language: Language,
    detections: Sequence[Detection] | None = None,
    client: LLMClient | None = None,
    allow_llm: bool = True,
) -> LocalizedAnalysis | None:
    """`analysis` rendered in `language`, or `None` when there is no analysis.

    `detections` lets a caller that already loaded them (the report dataset loads every board's
    detections anyway) skip the query the baseline rebuild needs. `client` is likewise for
    callers translating several boards in one pass, so one client is built for the batch rather
    than one per board.

    `allow_llm=False` restricts this to the free paths (cache and baseline rebuild). The
    interactive analysis screen uses it: a request that would otherwise block for the minutes a
    local CPU model takes to answer is not something to hang a page load on.
    """
    if analysis is None:
        return None
    source = _stored(analysis)
    if not source.per_defect:
        return source

    # The rebuild runs even when the stored language already matches, because a baseline's prose
    # *is* the catalogue and the row only holds the copy that was current the day the board was
    # inspected. Reading it from the catalogue instead means a correction to the wording reaches
    # every board already in the database, which is how the defect class names stopped being
    # translated on boards inspected before that was fixed, with no data migration. Only
    # `severity` is kept from the row, since a reviewer may have corrected it (FR-10).
    if analysis.source is AnalysisSource.KNOWLEDGE_BASE:
        if detections is None:
            detections = (
                await db.scalars(select(Detection).where(Detection.image_id == analysis.image_id))
            ).all()
        rebuilt = _rebuild_baseline(analysis, detections, language)
        if rebuilt is not None:
            return rebuilt

    if source.language is language:
        return source

    cached = _cached(analysis, language)
    if cached is not None:
        return cached
    if not allow_llm:
        return source

    # The `chat` role, not `report`, even though a report is the usual trigger: translating
    # prose that another model already validated is the cheapest thing this system asks of an
    # LLM, and the chat tier is deliberately the fastest/cheapest endpoint configured.
    client = client or await build_llm_client(db, role="chat")
    if client is None:
        logger.info(
            "No analysis model configured; analysis %s stays in %s", analysis.id, source.language
        )
        return source

    translated = await _translate(source, language, client)
    if translated is None:
        return source

    _store_in_cache(analysis, translated)
    await db.commit()
    return translated


async def localize_analyses(
    db: AsyncSession,
    analyses: Sequence[Analysis],
    *,
    language: Language,
    detections_by_image: Mapping[uuid.UUID, Sequence[Detection]] | None = None,
) -> dict[uuid.UUID, LocalizedAnalysis]:
    """`localize_analysis` over a whole report's worth of boards, keyed by analysis id.

    The LLM client is built once for the set, and only when something in it actually needs
    translating, so a Portuguese report over baseline-only boards never touches the network.
    """
    needs_llm = any(
        analysis_language(analysis) is not language
        and analysis.source is not AnalysisSource.KNOWLEDGE_BASE
        and _cached(analysis, language) is None
        for analysis in analyses
    )
    client = await build_llm_client(db, role="chat") if needs_llm else None

    localized: dict[uuid.UUID, LocalizedAnalysis] = {}
    for analysis in analyses:
        result = await localize_analysis(
            db,
            analysis,
            language=language,
            detections=(detections_by_image or {}).get(analysis.image_id),
            client=client,
        )
        if result is not None:
            localized[analysis.id] = result
    return localized
