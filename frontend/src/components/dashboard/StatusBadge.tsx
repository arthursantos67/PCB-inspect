"use client";

import { useI18n } from "@/contexts/I18nContext";
import { LampChip, type LampTone } from "@/components/ui/lamp-chip";
import type { ImageStatus } from "@/lib/api-client";

// Labels say what stage the board is at, not what the backend enum is called:
// "Detected" and "Completed" read as two ways of saying
// finished, and "Processing" and "Analyzing" as two ways of saying running, which left the
// operator unable to tell the four apart. The wording of each step, and the one-sentence
// description behind it, live in the dictionaries under `status.` / `statusDescription.`.

// Fixed enumeration order for status filter dropdowns (FE-04), following the pipeline order.
export const IMAGE_STATUSES: readonly ImageStatus[] = [
  "QUEUED",
  "PROCESSING",
  "DETECTED",
  "ANALYZING",
  "COMPLETED",
  "FAILED",
];

/** Lamp per status. Only the two terminal states earn a status color: a board that is still
 * moving through the pipeline is not a warning, so the in-progress states get a graphite lamp
 * that pulses, and the queue gets an unlit one. That way a column of statuses reads as
 * "finished / failed / still running" before any word is read.
 */
const STATUS_LAMP: Record<ImageStatus, { tone: LampTone; pulse?: boolean; hollow?: boolean }> = {
  QUEUED: { tone: "neutral", hollow: true },
  PROCESSING: { tone: "neutral", pulse: true },
  DETECTED: { tone: "neutral", pulse: true },
  ANALYZING: { tone: "neutral", pulse: true },
  COMPLETED: { tone: "good" },
  FAILED: { tone: "critical" },
};

/** Processing-status chip (FE-02/FE-10) — the label text is always self-describing, so a
 * status is never conveyed by color alone.
 */
export function StatusBadge({ status }: { status: ImageStatus }) {
  const { t } = useI18n();
  return (
    <LampChip {...STATUS_LAMP[status]} title={t(`statusDescription.${status}`)}>
      {t(`status.${status}`)}
    </LampChip>
  );
}

/** Expandable legend for the six statuses. Collapsed by
 * default so it explains the filter without competing with the results for space.
 */
export function StatusLegend({ className }: { className?: string }) {
  const { t } = useI18n();
  return (
    <details className={className}>
      <summary className="inline-flex cursor-pointer items-center text-[0.8125rem] text-muted-foreground transition-colors hover:text-foreground">
        {t("status.legendSummary")}
      </summary>
      <dl className="mt-3 grid grid-cols-1 gap-x-8 gap-y-2.5 rounded-md border border-border bg-card p-4 sm:grid-cols-2">
        {IMAGE_STATUSES.map((status) => (
          <div key={status} className="flex items-start gap-2.5">
            <dt className="shrink-0">
              <StatusBadge status={status} />
            </dt>
            <dd className="text-[0.8125rem] leading-relaxed text-muted-foreground">
              {t(`statusDescription.${status}`)}
            </dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
