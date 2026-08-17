"use client";

import { useI18n } from "@/contexts/I18nContext";
import type { TrendPeriod } from "@/lib/api-client";

// The labels stay "7d"/"30d"/"90d" in both languages: they are read as instrument markings,
// not as words. The spelled-out period behind each one is what gets translated.
const OPTIONS: { value: TrendPeriod; label: string }[] = [
  { value: "7d", label: "7d" },
  { value: "30d", label: "30d" },
  { value: "90d", label: "90d" },
];

/** Segmented range control (FE-02) — plain buttons rather than a dropdown, so every option
 * is one Tab stop away and needs no arrow-key convention to operate (FE-10). Set in the
 * instrument face, since a range is a setting on the reading.
 */
export function PeriodSelector({
  value,
  onChange,
}: {
  value: TrendPeriod;
  onChange: (period: TrendPeriod) => void;
}) {
  const { t } = useI18n();
  return (
    <div
      role="group"
      aria-label={t("dashboard.period.group")}
      className="inline-flex items-center gap-0.5 rounded-md border border-border bg-muted/70 p-[3px]"
    >
      {OPTIONS.map((option) => {
        const active = value === option.value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            title={t(`dashboard.period.${option.value}`)}
            onClick={() => onChange(option.value)}
            className={`readout rounded-[4px] px-2 py-1 text-[0.6875rem] font-medium transition-colors ${
              active
                ? "bg-card text-foreground shadow-panel"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
