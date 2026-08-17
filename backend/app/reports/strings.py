"""Every piece of fixed wording a generated report can contain, in both supported languages.

A report is generated in the station's language (or an explicit override), so headings, table
headers, KPI labels and the fallback narrative all have to exist twice. Only text the *report
itself* authors lives here.

The per board analysis prose is not here because it is not fixed wording: it is whatever the
agent chain wrote for that board. It originally shipped verbatim, which meant a Portuguese
report could carry English analysis paragraphs; issue #50 replaced that with a real
translation of the stored text (`app.analyses.localization`), cached per analysis so the cost
is paid once rather than per report.

`translate` falls back to English for a missing key rather than raising: a report that renders
one heading in the wrong language is still a usable report, an exception at generation time is
a FAILED row the operator cannot do anything about.
"""

import enum

from app.agents.prompts.v1 import POSITION_ZONE_EN, position_zone
from app.core.language import Language
from app.models.enums import (
    AnalysisReviewStatus,
    BoardDispositionDecision,
    DetectionReview,
    DetectionSource,
    DispositionRecommendation,
    ImageStatus,
    Severity,
)

# The report's language is the station's language (`app.core.language`), not a separate
# vocabulary: the alias keeps the reports code reading as "the language this report is in"
# while there is only ever one set of supported languages to keep in sync.
ReportLanguage = Language


NOT_AVAILABLE = "not_available"

_EN: dict[str, str] = {
    # Titles and cover.
    "title.individual": "Board Inspection Report",
    "title.consolidated": "Batch Inspection Report",
    "title.executive": "Executive Summary Report",
    "meta.generated_at": "Generated at",
    "meta.scope": "Scope",
    "meta.period": "Period",
    "meta.batch": "Batch",
    "meta.board": "Board",
    "meta.boards_in_report": "Boards in this report",
    "meta.narrative_source": "Written by",
    "meta.narrative_llm": "analysis model",
    "meta.narrative_computed": "computed from the recorded data",
    "scope.batch": "Batch {batch}",
    "scope.board": "Batch {batch}, board {board}",
    "scope.all": "All inspections matching the requested filters",
    "period.all_time": "All time",
    "period.range": "{start} to {end}",
    "period.earliest": "earliest",
    "period.latest": "latest",
    # Sections.
    "toc.title": "Contents",
    "section.summary": "Executive summary",
    "section.kpis": "Key figures",
    "section.frequency": "Defect frequency across the batch",
    "section.frequency_period": "Defect frequency in the period",
    "section.boards": "Boards",
    "section.board_overview": "Boards at a glance",
    "section.detections": "Detections",
    "section.analysis": "Analysis of each occurrence",
    "section.recommendations": "Recommended actions",
    "section.top_batches": "Batches with the most defects",
    "section.disposition": "Board decision",
    # Key figures.
    "kpi.boards_inspected": "Boards inspected",
    "kpi.boards_with_defects": "Boards with at least one defect",
    "kpi.defect_rate": "Share of boards with defects",
    "kpi.total_defects": "Reported defects",
    "kpi.aggregated_severity": "Aggregated severity",
    "kpi.defect_classes": "Distinct defect classes",
    "kpi.quality_rate": "Quality rate",
    "kpi.total_inspected": "Total inspected",
    "kpi.last_24h": "Inspected in the last 24h",
    "kpi.analyses_validated": "Analyses validated",
    "kpi.analyses_rejected": "Analyses rejected",
    "kpi.precision_rate": "Analysis precision rate",
    # Table headers.
    "col.defect_type": "Defect type",
    "col.occurrences": "Occurrences",
    "col.boards_affected": "Boards affected",
    "col.share_of_boards": "Share of boards",
    "col.share_of_defects": "Share of defects",
    "col.confidence": "Confidence",
    "col.review": "Review",
    "col.source": "Source",
    "col.position": "Position on the board",
    "col.severity": "Severity",
    "col.batch": "Batch",
    "col.board": "Board",
    "col.status": "Status",
    "col.created_at": "Inspected at",
    "col.processed_at": "Finished at",
    "col.defects": "Defects",
    "col.count": "Count",
    "col.occurrence": "Occurrence",
    "col.description": "Description",
    "col.probable_causes": "Probable causes",
    "col.suggested_solutions": "Suggested solutions",
    "col.disposition": "Board decision",
    "col.disposition_recommendation": "Recommended decision",
    "col.review_status": "Analysis review",
    "col.inspection_id": "Inspection id",
    "col.value": "Value",
    "col.metric": "Metric",
    # Inline labels.
    "label.causes": "Probable causes",
    "label.solutions": "Suggested solutions",
    "label.severity": "Severity",
    "label.confidence": "Confidence",
    "label.recommendation": "Recommended decision",
    "label.board_analysis": "Board summary",
    "occurrence.heading": "Occurrence {index} of {total}, {defect} at the {position}",
    "position.phrase": (
        "{zone}, centred at x={x} y={y} of the board, box {width} wide and {height} tall"
    ),
    "occurrence.no_analysis": (
        "No agent analysis is on record for this occurrence, so only the detector's own "
        "figures are reported above."
    ),
    # Notes and empty states.
    "note.no_defects": "No reported defects on the boards covered by this report.",
    "note.no_boards": "No board matched the filters used to generate this report.",
    "note.boards_without_defects": (
        "{count} board(s) in this report have no reported defect and are listed in the table "
        "above only."
    ),
    "note.detail_truncated": (
        "Detailed sections are shown for the first {shown} of {total} boards carrying defects. "
        "Generate the CSV version of this report for the complete, machine readable set."
    ),
    "note.no_recommendations": "No specific action is recommended for this scope.",
    "note.not_available": "not available",
    # Only rendered when a board's analysis could not be translated into the report's language
    # (issue #50) — normally nothing in a report is in another language at all.
    "note.analysis_not_translated": (
        "The analysis below is reproduced in {written_in}, the language it was written in: no "
        "analysis model was reachable to translate it when this report was generated."
    ),
    "language.en": "English",
    "language.pt": "Portuguese",
    "footer.page": "Page {page} of {total}",
    # Deterministic narrative, used when no analysis model is reachable.
    "fallback.overview_boards": (
        "{boards_with_defects} of the {boards_total} board(s) covered by this report carry at "
        "least one reported defect, {defect_rate} of the boards inspected, for a total of "
        "{defect_total} occurrence(s) across {classes} defect class(es). The aggregated "
        "severity of the scope is {severity}."
    ),
    "fallback.overview_clean": (
        "None of the {boards_total} board(s) covered by this report carry a reported defect."
    ),
    "fallback.note_isolated": (
        "{defect} appears {occurrences} time(s) on {boards} board(s) out of {boards_total}. At "
        "that frequency it reads as an isolated occurrence rather than a pattern, so the local "
        "explanations for the class come first and a process wide cause is not supported by "
        "these counts alone."
    ),
    "fallback.note_recurring": (
        "{defect} appears {occurrences} time(s) on {boards} board(s) out of {boards_total}, "
        "{share} of the batch. A defect repeating on that share of the boards points at "
        "something shared upstream rather than at each board individually, though the counts "
        "are evidence and not proof, so the simpler local causes stay on the table."
    ),
    "fallback.recommendation_review": (
        "Review the {defect} occurrences against the process step that produces them before "
        "releasing the batch."
    ),
    "fallback.recommendation_disposition": (
        "{count} board(s) still have no recorded decision, so close them out as approved, "
        "rework or scrapped."
    ),
    "fallback.recommendation_validate": (
        "{count} analysis/analyses are still awaiting operator review."
    ),
}

_PT: dict[str, str] = {
    "title.individual": "Relatório de Inspeção da Placa",
    "title.consolidated": "Relatório de Inspeção do Lote",
    "title.executive": "Relatório Executivo",
    "meta.generated_at": "Gerado em",
    "meta.scope": "Escopo",
    "meta.period": "Período",
    "meta.batch": "Lote",
    "meta.board": "Placa",
    "meta.boards_in_report": "Placas neste relatório",
    "meta.narrative_source": "Texto produzido por",
    "meta.narrative_llm": "modelo de análise",
    "meta.narrative_computed": "cálculo sobre os dados registrados",
    "scope.batch": "Lote {batch}",
    "scope.board": "Lote {batch}, placa {board}",
    "scope.all": "Todas as inspeções que atendem aos filtros solicitados",
    "period.all_time": "Todo o período",
    "period.range": "{start} até {end}",
    "period.earliest": "início",
    "period.latest": "hoje",
    "toc.title": "Sumário",
    "section.summary": "Resumo executivo",
    "section.kpis": "Números principais",
    "section.frequency": "Frequência dos defeitos no lote",
    "section.frequency_period": "Frequência dos defeitos no período",
    "section.boards": "Placas",
    "section.board_overview": "Visão geral das placas",
    "section.detections": "Detecções",
    "section.analysis": "Análise de cada ocorrência",
    "section.recommendations": "Ações recomendadas",
    "section.top_batches": "Lotes com mais defeitos",
    "section.disposition": "Decisão sobre a placa",
    "kpi.boards_inspected": "Placas inspecionadas",
    "kpi.boards_with_defects": "Placas com ao menos um defeito",
    "kpi.defect_rate": "Percentual de placas com defeito",
    "kpi.total_defects": "Defeitos reportados",
    "kpi.aggregated_severity": "Severidade agregada",
    "kpi.defect_classes": "Classes de defeito distintas",
    "kpi.quality_rate": "Taxa de qualidade",
    "kpi.total_inspected": "Total inspecionado",
    "kpi.last_24h": "Inspecionadas nas últimas 24h",
    "kpi.analyses_validated": "Análises validadas",
    "kpi.analyses_rejected": "Análises rejeitadas",
    "kpi.precision_rate": "Taxa de acerto das análises",
    "col.defect_type": "Tipo de defeito",
    "col.occurrences": "Ocorrências",
    "col.boards_affected": "Placas afetadas",
    "col.share_of_boards": "Percentual das placas",
    "col.share_of_defects": "Percentual dos defeitos",
    "col.confidence": "Confiança",
    "col.review": "Revisão",
    "col.source": "Origem",
    "col.position": "Posição na placa",
    "col.severity": "Severidade",
    "col.batch": "Lote",
    "col.board": "Placa",
    "col.status": "Status",
    "col.created_at": "Inspecionada em",
    "col.processed_at": "Concluída em",
    "col.defects": "Defeitos",
    "col.count": "Quantidade",
    "col.occurrence": "Ocorrência",
    "col.description": "Descrição",
    "col.probable_causes": "Causas prováveis",
    "col.suggested_solutions": "Soluções sugeridas",
    "col.disposition": "Decisão sobre a placa",
    "col.disposition_recommendation": "Decisão recomendada",
    "col.review_status": "Revisão da análise",
    "col.inspection_id": "Id da inspeção",
    "col.value": "Valor",
    "col.metric": "Indicador",
    "label.causes": "Causas prováveis",
    "label.solutions": "Soluções sugeridas",
    "label.severity": "Severidade",
    "label.confidence": "Confiança",
    "label.recommendation": "Decisão recomendada",
    "label.board_analysis": "Resumo da placa",
    "occurrence.heading": "Ocorrência {index} de {total}, {defect} na {position}",
    "position.phrase": (
        "{zone}, com centro em x={x} y={y} da placa, caixa de {width} de largura por "
        "{height} de altura"
    ),
    "occurrence.no_analysis": (
        "Não há análise dos agentes registrada para esta ocorrência, portanto apenas os "
        "números do detector aparecem acima."
    ),
    "note.no_defects": "Nenhum defeito reportado nas placas cobertas por este relatório.",
    "note.no_boards": "Nenhuma placa atendeu aos filtros usados para gerar este relatório.",
    "note.boards_without_defects": (
        "{count} placa(s) deste relatório não têm defeito reportado e aparecem apenas na "
        "tabela acima."
    ),
    "note.detail_truncated": (
        "As seções detalhadas cobrem as primeiras {shown} de {total} placas com defeito. Gere "
        "a versão CSV deste relatório para obter o conjunto completo."
    ),
    "note.no_recommendations": "Nenhuma ação específica é recomendada para este escopo.",
    "note.not_available": "não disponível",
    "note.analysis_not_translated": (
        "A análise a seguir está reproduzida em {written_in}, o idioma em que foi escrita: "
        "nenhum modelo de análise estava acessível para traduzi-la quando este relatório foi "
        "gerado."
    ),
    "language.en": "inglês",
    "language.pt": "português",
    "footer.page": "Página {page} de {total}",
    "fallback.overview_boards": (
        "{boards_with_defects} das {boards_total} placa(s) cobertas por este relatório têm ao "
        "menos um defeito reportado, {defect_rate} das placas inspecionadas, somando "
        "{defect_total} ocorrência(s) em {classes} classe(s) de defeito. A severidade agregada "
        "do escopo é {severity}."
    ),
    "fallback.overview_clean": (
        "Nenhuma das {boards_total} placa(s) cobertas por este relatório tem defeito reportado."
    ),
    "fallback.note_isolated": (
        "{defect} aparece {occurrences} vez(es) em {boards} placa(s) de {boards_total}. Nessa "
        "frequência o caso se parece mais com uma ocorrência isolada do que com um padrão, "
        "então as explicações locais da classe vêm primeiro e uma causa de processo não se "
        "sustenta apenas com esses números."
    ),
    "fallback.note_recurring": (
        "{defect} aparece {occurrences} vez(es) em {boards} placa(s) de {boards_total}, "
        "{share} do lote. Um defeito que se repete nessa proporção das placas aponta para algo "
        "compartilhado no processo e não para cada placa isoladamente, ainda que os números "
        "sejam indício e não prova, de modo que as causas locais mais simples continuam "
        "válidas."
    ),
    "fallback.recommendation_review": (
        "Revise as ocorrências de {defect} junto à etapa do processo que as produz antes de "
        "liberar o lote."
    ),
    "fallback.recommendation_disposition": (
        "{count} placa(s) ainda estão sem decisão registrada, portanto conclua cada uma como "
        "aprovada, retrabalho ou sucateada."
    ),
    "fallback.recommendation_validate": (
        "{count} análise(s) ainda aguardam revisão do operador."
    ),
}

_CATALOG: dict[ReportLanguage, dict[str, str]] = {ReportLanguage.EN: _EN, ReportLanguage.PT: _PT}

# `DefectType` is deliberately absent from `_ENUM_PT` below. The defect classes keep their
# names in every language, on every surface: the screens, the charts, the stored analyses and
# the chat all show the class the model itself emits, and a Portuguese report that renamed them
# would be the only place in the application calling the same defect something else.
_SEVERITY_PT: dict[Severity, str] = {
    Severity.LOW: "baixa",
    Severity.MEDIUM: "média",
    Severity.HIGH: "alta",
    Severity.CRITICAL: "crítica",
}

_STATUS_PT: dict[ImageStatus, str] = {
    ImageStatus.QUEUED: "na fila",
    ImageStatus.PROCESSING: "detectando",
    ImageStatus.DETECTED: "detectada",
    ImageStatus.ANALYZING: "analisando",
    ImageStatus.COMPLETED: "concluída",
    ImageStatus.FAILED: "falhou",
}

_DETECTION_REVIEW_PT: dict[DetectionReview, str] = {
    DetectionReview.UNREVIEWED: "sem revisão",
    DetectionReview.CONFIRMED: "confirmado",
    DetectionReview.FALSE_POSITIVE: "falso positivo",
}

_DETECTION_SOURCE_PT: dict[DetectionSource, str] = {
    DetectionSource.MODEL: "modelo",
    DetectionSource.MANUAL: "operador",
}

_ANALYSIS_REVIEW_PT: dict[AnalysisReviewStatus, str] = {
    AnalysisReviewStatus.PENDING: "pendente",
    AnalysisReviewStatus.VALIDATED: "validada",
    AnalysisReviewStatus.REJECTED: "rejeitada",
}

_DISPOSITION_PT: dict[BoardDispositionDecision, str] = {
    BoardDispositionDecision.APPROVED: "placa aprovada",
    BoardDispositionDecision.REWORK: "placa para retrabalho",
    BoardDispositionDecision.DISCARDED: "placa sucateada",
}

_RECOMMENDATION_PT: dict[DispositionRecommendation, str] = {
    DispositionRecommendation.APPROVE: "aprovar",
    DispositionRecommendation.REWORK: "retrabalhar",
    DispositionRecommendation.DISCARD: "sucatear",
}

_ENUM_PT: dict[type, dict[enum.Enum, str]] = {
    Severity: _SEVERITY_PT,  # type: ignore[dict-item]
    ImageStatus: _STATUS_PT,  # type: ignore[dict-item]
    DetectionReview: _DETECTION_REVIEW_PT,  # type: ignore[dict-item]
    DetectionSource: _DETECTION_SOURCE_PT,  # type: ignore[dict-item]
    AnalysisReviewStatus: _ANALYSIS_REVIEW_PT,  # type: ignore[dict-item]
    BoardDispositionDecision: _DISPOSITION_PT,  # type: ignore[dict-item]
    DispositionRecommendation: _RECOMMENDATION_PT,  # type: ignore[dict-item]
}


def translate(language: ReportLanguage, key: str, **params: object) -> str:
    template = _CATALOG[language].get(key) or _EN.get(key, key)
    return template.format(**params) if params else template


def label_enum(language: ReportLanguage, value: enum.Enum | None, *, fallback: str = "-") -> str:
    """A severity, status or decision in the report's language, or an enum with no translation
    at all, which reads its own value with underscores opened up — what the screens show.

    Defect classes take that second path in both languages, on purpose (`_ENUM_PT`).
    """
    if value is None:
        return fallback
    if language is ReportLanguage.PT:
        translated = _ENUM_PT.get(type(value), {}).get(value)
        if translated is not None:
            return translated
    return str(value.value).replace("_", " ")


_POSITION_ZONE_PT: dict[str, str] = {
    "centre": "região central da placa",
    "upper_left": "parte superior esquerda",
    "upper_centre": "parte superior central",
    "upper_right": "parte superior direita",
    "middle_left": "parte central esquerda",
    "middle_right": "parte central direita",
    "lower_left": "parte inferior esquerda",
    "lower_centre": "parte inferior central",
    "lower_right": "parte inferior direita",
}


def format_position(language: ReportLanguage, bbox: dict[str, float]) -> str:
    """Where a detection sits on the board, in the report's language.

    The phrase is computed at generation time from the bounding box, so unlike the stored
    analysis prose it is the report's own wording and follows the language the operator asked
    for. `app.agents.prompts.v1` builds the English version of the same phrase for the
    analysis prompts; both read the zone from `position_zone`, so the two can never disagree
    about where a defect is.
    """
    zone_key = position_zone(bbox)
    zone = (
        _POSITION_ZONE_PT.get(zone_key, zone_key)
        if language is ReportLanguage.PT
        else POSITION_ZONE_EN.get(zone_key, zone_key)
    )
    centre_x = (bbox["x1"] + bbox["x2"]) / 2
    centre_y = (bbox["y1"] + bbox["y2"]) / 2
    return translate(
        language,
        "position.phrase",
        zone=zone,
        x=f"{centre_x * 100:.0f}%",
        y=f"{centre_y * 100:.0f}%",
        width=format_percent(bbox["x2"] - bbox["x1"], language),
        height=format_percent(bbox["y2"] - bbox["y1"], language),
    )


def format_percent(value: float, language: ReportLanguage) -> str:
    """`value` is a 0..1 share. Portuguese writes the decimal comma."""
    text = f"{value * 100:.1f}%"
    return text.replace(".", ",") if language is ReportLanguage.PT else text


def format_decimal(value: float, language: ReportLanguage, *, places: int = 2) -> str:
    text = f"{value:.{places}f}"
    return text.replace(".", ",") if language is ReportLanguage.PT else text
