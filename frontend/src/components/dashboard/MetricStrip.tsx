"use client";

import { useI18n } from "@/contexts/I18nContext";
import { cn } from "@/lib/utils";

/** The throughput facts, laid out as one strip of readouts divided by hairline seams rather
 * than as separate floating cards. Four numbers that describe the same run belong on the
 * same instrument face; four cards with gutters between them read as four unrelated widgets.
 */
export function MetricStrip({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border shadow-panel lg:grid-cols-4">
      {children}
    </div>
  );
}

export function Metric({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string;
  hint?: string;
  /** `attention` tints the readout when the number is the one that means something is off. */
  tone?: "default" | "attention";
}) {
  return (
    <div className="flex min-w-0 flex-col justify-between gap-3 bg-card px-5 py-4">
      <p className="label-channel">{label}</p>
      <div className="min-w-0">
        <p
          className={cn(
            "readout truncate text-[1.75rem] leading-none font-semibold",
            tone === "attention" && "text-status-serious"
          )}
        >
          {value}
        </p>
        {hint ? (
          <p className="mt-2 truncate text-[0.75rem] text-muted-foreground" title={hint}>
            {hint}
          </p>
        ) : null}
      </div>
    </div>
  );
}

export function MetricSkeleton({ label }: { label: string }) {
  const { t } = useI18n();
  return (
    <div className="flex min-w-0 flex-col justify-between gap-3 bg-card px-5 py-4">
      <p className="label-channel">{label}</p>
      <div
        className="h-7 w-20 animate-pulse rounded-sm bg-muted"
        role="status"
        aria-label={t("dashboard.metric.loading", { label })}
      />
    </div>
  );
}
