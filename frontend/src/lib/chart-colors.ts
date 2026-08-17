// Fixed color assignment for the 6 defect classes (identity — categorical) and the 4
// severity levels (state — status palette), per the dataviz skill: categorical hues are
// assigned in a fixed order and never cycled or re-derived from a filtered subset.

export type DefectType =
  | "missing_hole"
  | "mouse_bite"
  | "open_circuit"
  | "short"
  | "spur"
  | "spurious_copper";

export const DEFECT_TYPES: readonly DefectType[] = [
  "missing_hole",
  "mouse_bite",
  "open_circuit",
  "short",
  "spur",
  "spurious_copper",
];

// Class and severity names live in the i18n dictionaries (`defect.*`, `severity.*`), not here:
// this module is the color contract, and a second copy of the words would go stale the moment
// one of them is reworded.

// Slot order fixed to the categorical palette's CVD-safe ordering (see globals.css --series-N).
// Green is excluded from this palette on purpose — it's reserved for the status-good state.
export const DEFECT_TYPE_COLOR: Record<DefectType, string> = {
  missing_hole: "var(--series-1)",
  mouse_bite: "var(--series-2)",
  open_circuit: "var(--series-3)",
  short: "var(--series-4)",
  spur: "var(--series-5)",
  spurious_copper: "var(--series-6)",
};

export type Severity = "low" | "medium" | "high" | "critical";

export const SEVERITIES: readonly Severity[] = ["low", "medium", "high", "critical"];

// Severity is a state, not an identity, so it draws from the reserved status palette
// (never the categorical series colors) — low->good ... critical->critical.
export const SEVERITY_COLOR: Record<Severity, string> = {
  low: "var(--status-good)",
  medium: "var(--status-warning)",
  high: "var(--status-serious)",
  critical: "var(--status-critical)",
};
