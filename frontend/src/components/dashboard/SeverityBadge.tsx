import { SEVERITY_COLOR, SEVERITY_LABEL, type Severity } from "@/lib/chart-colors";

/** Severity badge (FE-02/FE-10) — draws from the reserved status palette (never a
 * categorical series color), always paired with its text label.
 */
export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-xs font-medium whitespace-nowrap text-foreground">
      <span
        aria-hidden="true"
        className="size-2 shrink-0 rounded-full"
        style={{ backgroundColor: SEVERITY_COLOR[severity] }}
      />
      {SEVERITY_LABEL[severity]}
    </span>
  );
}
