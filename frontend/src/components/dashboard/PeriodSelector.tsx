"use client";

import { Button } from "@/components/ui/button";
import type { TrendPeriod } from "@/lib/api-client";

const OPTIONS: { value: TrendPeriod; label: string }[] = [
  { value: "7d", label: "7d" },
  { value: "30d", label: "30d" },
  { value: "90d", label: "90d" },
];

/** Segmented period control (FE-02) — plain buttons rather than a dropdown so every option
 * is reachable with a single Tab stop and arrow-free keyboard nav (FE-10).
 */
export function PeriodSelector({
  value,
  onChange,
}: {
  value: TrendPeriod;
  onChange: (period: TrendPeriod) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Trend period"
      className="inline-flex gap-0.5 rounded-lg border border-border p-0.5"
    >
      {OPTIONS.map((option) => (
        <Button
          key={option.value}
          type="button"
          size="sm"
          variant={value === option.value ? "secondary" : "ghost"}
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </Button>
      ))}
    </div>
  );
}
