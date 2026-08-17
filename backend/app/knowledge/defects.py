"""Static, curated knowledge base for the 6 fixed PCB defect classes (FR-06's baseline
tier): description, typical causes, standard solutions, and a default severity per class.

Looked up synchronously as a plain in-memory dict — no I/O, no LLM — so the baseline
analysis tier (`app.analyses.service`) never adds perceptible latency to the main
inspection flow (NFR-01).

Curated in both station languages (issue #50). Having the Portuguese written by hand here,
rather than machine translated later, is what lets a baseline analysis be *rebuilt* in either
language at read time (`app.analyses.localization`): its text is this catalogue verbatim, so
there is nothing to translate and no LLM call to pay for. Only the agent chain's own prose
needs real translation. `severity` is deliberately shared between the two: it is a
classification, not wording, and the two languages must never disagree about it.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from app.core.language import DEFAULT_LANGUAGE, Language
from app.models.enums import DefectType, Severity, severity_rank


@dataclass(frozen=True)
class DefectKnowledge:
    description: str
    probable_causes: tuple[str, ...]
    suggested_solutions: tuple[str, ...]
    severity: Severity


DEFECT_KNOWLEDGE_BASE: dict[DefectType, DefectKnowledge] = {
    DefectType.MISSING_HOLE: DefectKnowledge(
        description=(
            "A drilled or plated through-hole specified in the design is absent from the "
            "board, leaving no via or component mounting point where one is expected."
        ),
        probable_causes=(
            "Drill program mismatch with the Gerber/NC drill file",
            "Broken or skipped drill bit not flagged by the drilling machine",
            "Panel misalignment during the drilling pass",
        ),
        suggested_solutions=(
            "Cross-check the drill file against the board's hole count before re-running the panel",
            "Re-drill the affected coordinates if annular ring and copper clearance allow it",
            "Scrap and re-fabricate the board if the hole is load-bearing or on a critical net",
        ),
        severity=Severity.HIGH,
    ),
    DefectType.MOUSE_BITE: DefectKnowledge(
        description=(
            "Small semicircular notches along a copper pad or trace edge, resembling bites "
            "taken out of the copper — typically from incomplete etching or routing breakout."
        ),
        probable_causes=(
            "Etching process under- or over-etching at the panel's routing breakout tabs",
            "Router bit chatter or worn tooling along the board outline",
            "Insufficient copper-to-edge clearance in the panelization design",
        ),
        suggested_solutions=(
            "Inspect trace continuity and copper thickness at the site under magnification",
            "Rework by cleaning and re-plating the notch if it does not breach minimum trace width",
            "Adjust panelization breakout tab placement and re-fabricate for recurring cases",
        ),
        severity=Severity.LOW,
    ),
    DefectType.OPEN_CIRCUIT: DefectKnowledge(
        description=(
            "A break in a conductive trace that interrupts electrical continuity along a "
            "net, isolating one or more components from the rest of the circuit."
        ),
        probable_causes=(
            "Etching over-etch removing copper below the minimum trace width",
            "Physical damage to the trace during handling, drilling, or routing",
            "Contamination or resist defect during the copper patterning step",
        ),
        suggested_solutions=(
            "Verify net continuity with a continuity tester against the schematic",
            "Rework with a jumper wire or conductive-ink trace repair where accessible",
            "Reject the board if the open is on an inner layer or a high-current net",
        ),
        severity=Severity.CRITICAL,
    ),
    DefectType.SHORT: DefectKnowledge(
        description=(
            "An unintended conductive bridge between two traces or pads that should remain "
            "electrically isolated, creating an unwanted low-impedance path."
        ),
        probable_causes=(
            "Etching under-etch leaving residual copper between adjacent features",
            "Solder bridging from a prior assembly pass on a reused/reflowed panel",
            "Foreign conductive debris trapped during lamination or plating",
        ),
        suggested_solutions=(
            "Isolate the bridge and verify with a continuity/resistance check between the nets",
            "Rework by manually removing the excess copper with a scalpel or micro-router",
            "Reject the board if the short is on an inner layer or a power/ground plane",
        ),
        severity=Severity.CRITICAL,
    ),
    DefectType.SPUR: DefectKnowledge(
        description=(
            "An unwanted, unconnected sliver of copper projecting from a trace or pad edge, "
            "left behind by incomplete etching."
        ),
        probable_causes=(
            "Etching resist artifact or under-etch leaving stray copper",
            "Photoresist film defect (pinhole or debris) during exposure",
            "Gerber-to-film registration error",
        ),
        suggested_solutions=(
            "Verify the spur does not reduce clearance below the design rule to a neighboring net",
            "Rework by trimming the copper sliver under magnification if clearance is marginal",
            "Accept as cosmetic if clearance and creepage margins are unaffected",
        ),
        severity=Severity.LOW,
    ),
    DefectType.SPURIOUS_COPPER: DefectKnowledge(
        description=(
            "An isolated island or patch of copper present on the board with no "
            "corresponding feature in the design, unconnected to any net."
        ),
        probable_causes=(
            "Etching resist defect leaving an unintended copper island",
            "Debris or contamination on the panel during the imaging/exposure step",
            "Film-to-panel registration error during photoprinting",
        ),
        suggested_solutions=(
            "Confirm the island is electrically isolated from all nets before dispositioning",
            "Rework by removing the copper patch if it risks contact with a neighboring feature",
            "Accept as cosmetic if clearance to all nets meets the design rule",
        ),
        severity=Severity.MEDIUM,
    ),
}


_KNOWLEDGE_PT: dict[DefectType, DefectKnowledge] = {
    DefectType.MISSING_HOLE: DefectKnowledge(
        description=(
            "Um furo passante, metalizado ou não, previsto no projeto está ausente da placa, "
            "deixando sem via nem ponto de fixação um local onde o desenho exige um."
        ),
        probable_causes=(
            "Divergência entre o programa de furação e o arquivo Gerber/NC drill",
            "Broca quebrada ou furo pulado sem sinalização pela furadeira",
            "Desalinhamento do painel durante a etapa de furação",
        ),
        suggested_solutions=(
            "Conferir o arquivo de furação contra a contagem de furos da placa antes de refazer "
            "o painel",
            "Refurar as coordenadas afetadas se o anel anular e o isolamento do cobre permitirem",
            "Sucatear e refabricar a placa se o furo for estrutural ou pertencer a uma rede "
            "crítica",
        ),
        severity=Severity.HIGH,
    ),
    DefectType.MOUSE_BITE: DefectKnowledge(
        description=(
            "Pequenos entalhes semicirculares na borda de uma ilha ou trilha de cobre, com "
            "aparência de mordidas, em geral resultantes de corrosão incompleta ou do "
            "destacamento das abas de roteamento."
        ),
        probable_causes=(
            "Corrosão insuficiente ou excessiva nas abas de destacamento do painel",
            "Trepidação da fresa ou ferramenta desgastada ao longo do contorno da placa",
            "Isolamento insuficiente entre cobre e borda no projeto de panelização",
        ),
        suggested_solutions=(
            "Inspecionar a continuidade da trilha e a espessura do cobre no local sob ampliação",
            "Retrabalhar limpando e remetalizando o entalhe se ele não reduzir a trilha abaixo "
            "da largura mínima",
            "Ajustar a posição das abas de destacamento e refabricar quando o caso for recorrente",
        ),
        severity=Severity.LOW,
    ),
    DefectType.OPEN_CIRCUIT: DefectKnowledge(
        description=(
            "Interrupção em uma trilha condutora que quebra a continuidade elétrica de uma "
            "rede, isolando um ou mais componentes do restante do circuito."
        ),
        probable_causes=(
            "Corrosão excessiva removendo cobre abaixo da largura mínima de trilha",
            "Dano físico à trilha durante manuseio, furação ou roteamento",
            "Contaminação ou falha do fotorresiste na etapa de definição do cobre",
        ),
        suggested_solutions=(
            "Verificar a continuidade da rede com um teste de continuidade contra o esquemático",
            "Retrabalhar com fio jumper ou reparo com tinta condutiva onde houver acesso",
            "Rejeitar a placa se a interrupção estiver em camada interna ou em rede de alta "
            "corrente",
        ),
        severity=Severity.CRITICAL,
    ),
    DefectType.SHORT: DefectKnowledge(
        description=(
            "Ponte condutora indevida entre duas trilhas ou ilhas que deveriam permanecer "
            "eletricamente isoladas, criando um caminho de baixa impedância não previsto."
        ),
        probable_causes=(
            "Corrosão insuficiente deixando cobre residual entre feições adjacentes",
            "Ponte de solda remanescente de uma montagem anterior no painel reaproveitado",
            "Detrito condutivo aprisionado durante a laminação ou a metalização",
        ),
        suggested_solutions=(
            "Isolar a ponte e confirmar com medição de continuidade ou resistência entre as redes",
            "Retrabalhar removendo o excesso de cobre com bisturi ou microfresa",
            # A classe se chama `short` em qualquer idioma: é o nome que o detector, as tabelas
            # do relatório e os gráficos usam, e traduzir aqui faria o texto sugerido discordar
            # da tabela impressa ao lado dele.
            "Rejeitar a placa se o short estiver em camada interna ou em plano de alimentação "
            "ou terra",
        ),
        severity=Severity.CRITICAL,
    ),
    DefectType.SPUR: DefectKnowledge(
        description=(
            "Farpa de cobre indesejada e sem conexão, projetando-se da borda de uma trilha ou "
            "ilha, deixada por corrosão incompleta."
        ),
        probable_causes=(
            "Artefato do fotorresiste ou corrosão insuficiente deixando cobre residual",
            "Defeito no filme fotorresiste, como furo de agulha ou sujeira, durante a exposição",
            "Erro de registro entre o Gerber e o filme",
        ),
        suggested_solutions=(
            "Verificar se a farpa não reduz o isolamento até a rede vizinha abaixo da regra de "
            "projeto",
            "Retrabalhar aparando a farpa de cobre sob ampliação quando o isolamento estiver no "
            "limite",
            "Aceitar como defeito cosmético se as margens de isolamento e de fuga não forem "
            "afetadas",
        ),
        severity=Severity.LOW,
    ),
    DefectType.SPURIOUS_COPPER: DefectKnowledge(
        description=(
            "Ilha ou mancha isolada de cobre presente na placa sem feição correspondente no "
            "projeto, sem ligação com nenhuma rede."
        ),
        probable_causes=(
            "Falha do fotorresiste na corrosão, deixando uma ilha de cobre não prevista",
            "Detrito ou contaminação sobre o painel na etapa de exposição",
            "Erro de registro entre filme e painel durante a fotoimpressão",
        ),
        suggested_solutions=(
            "Confirmar que a ilha está eletricamente isolada de todas as redes antes de decidir "
            "o destino da placa",
            "Retrabalhar removendo a mancha de cobre se houver risco de contato com uma feição "
            "vizinha",
            "Aceitar como defeito cosmético se o isolamento para todas as redes atender à regra "
            "de projeto",
        ),
        severity=Severity.MEDIUM,
    ),
}

_CATALOG: dict[Language, dict[DefectType, DefectKnowledge]] = {
    Language.EN: DEFECT_KNOWLEDGE_BASE,
    Language.PT: _KNOWLEDGE_PT,
}


def knowledge_base(language: Language) -> dict[DefectType, DefectKnowledge]:
    """The curated catalogue in `language`, falling back to English for anything unsupported.

    `DEFECT_KNOWLEDGE_BASE` stays the English dict rather than becoming a function call: the
    agent prompts and the severity policy read it dozens of times and are English-only by
    design (the prompts reason in English and emit prose in the station's language).
    """
    return _CATALOG.get(language, _CATALOG[DEFAULT_LANGUAGE])


DEFECT_TYPE_WEIGHT: dict[DefectType, int] = {
    defect_type: severity_rank(knowledge.severity) + 1
    for defect_type, knowledge in DEFECT_KNOWLEDGE_BASE.items()
}
"""Per-defect-type weight (1..4, low..critical) derived from each class's default severity
above — reused by `severity_from_defect_counts` below to compute a batch's aggregated
severity instead of a plain defect-rate threshold, so e.g. a
batch dominated by `open_circuit`/`short` (critical) reads as worse than one with the same
defect count made up mostly of `mouse_bite`/`spur` (low).
"""

# A weighted-severity score is bounded to [min(weight), max(weight)] = [1, 4] since it's a
# weighted average over proportions that sum to 1 — split that range into four equal bands.
_WEIGHT_MIN = min(DEFECT_TYPE_WEIGHT.values())
_WEIGHT_MAX = max(DEFECT_TYPE_WEIGHT.values())
_BAND_WIDTH = (_WEIGHT_MAX - _WEIGHT_MIN) / 4

# How much of the composition score survives when *no* board in the group is defective, i.e.
# the floor of the defect-rate factor below. Not zero: a critical defect class is still a
# critical finding on the boards that carry it, so scale can lower the reading by at most one
# half, never erase what was found (see `severity_from_defect_counts`).
_RATE_FLOOR = 0.5


def severity_from_defect_counts(
    counts: Mapping[DefectType, int], *, defect_rate: float
) -> Severity | None:
    """A group of defects' aggregated severity, from two factors, banded back into a
    `Severity`. `None` when the group has no defects at all.

    1. *What* was found: each defect type's share of the group's total, weighted by that
       type's `DEFECT_TYPE_WEIGHT` and summed, so a batch dominated by `open_circuit`/`short`
       reads as worse than one with the same defect count made up of `mouse_bite`/`spur`.
    2. *How widespread* it is: `defect_rate`, the share of inspected boards in the group
       carrying at least one reported defect (0..1). Two defective boards out of 500 is a
       different finding from 400 out of 500 even when both carry the same defect class, and
       composition alone cannot tell them apart.

    The two are combined as `composition * (0.5 + 0.5 * defect_rate)` rather than multiplied
    outright: a bare product would collapse every realistic batch into `low`, since defect
    rates on a working line sit near zero, which would make the whole reading useless.

    Shared by the dashboard's recent-batches card, the batch list, the reports' analytics and
    the chat agent's batch tools, so all of them read the same way for the same data.
    """
    total = sum(counts.values())
    if total <= 0:
        return None
    composition = sum(
        (count / total) * DEFECT_TYPE_WEIGHT[defect_type] for defect_type, count in counts.items()
    )
    rate = min(max(defect_rate, 0.0), 1.0)
    score = composition * (_RATE_FLOOR + (1 - _RATE_FLOOR) * rate)
    if score < _WEIGHT_MIN + _BAND_WIDTH:
        return Severity.LOW
    if score < _WEIGHT_MIN + 2 * _BAND_WIDTH:
        return Severity.MEDIUM
    if score < _WEIGHT_MIN + 3 * _BAND_WIDTH:
        return Severity.HIGH
    return Severity.CRITICAL
