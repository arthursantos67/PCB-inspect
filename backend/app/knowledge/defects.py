"""Static, curated knowledge base for the 6 fixed PCB defect classes (FR-06's baseline
tier): description, typical causes, standard solutions, and a default severity per class.

Looked up synchronously as a plain in-memory dict — no I/O, no LLM — so the baseline
analysis tier (`app.analyses.service`) never adds perceptible latency to the main
inspection flow (NFR-01).
"""

from dataclasses import dataclass

from app.models.enums import DefectType, Severity


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
