"use client";

import { useI18n } from "@/contexts/I18nContext";
import { SEVERITY_COLOR, type Severity } from "@/lib/chart-colors";

/** Severity chip (FE-02/FE-10) — draws from the reserved status palette (never a
 * categorical series color), always paired with its text label. The swatch is tinted behind
 * the label as well as marked in front of it, so scanning a column of severities gives a
 * shape even before the words are read.
 */
export function SeverityBadge({ severity }: { severity: Severity }) {
  const { t } = useI18n();
  const color = SEVERITY_COLOR[severity];
  return (
    <span
      className="inline-flex h-[1.375rem] items-center gap-1.5 rounded-[5px] border px-1.5 text-[0.6875rem] font-medium whitespace-nowrap text-foreground"
      style={{
        borderColor: `color-mix(in oklch, ${color} 32%, transparent)`,
        backgroundColor: `color-mix(in oklch, ${color} 9%, transparent)`,
      }}
    >
      <span
        aria-hidden="true"
        className="size-2 shrink-0 rounded-[2px]"
        style={{ backgroundColor: color }}
      />
      {t(`severity.${severity}`)}
    </span>
  );
}
