"use client";

import { ChartDataTable, ChartPlaceholder } from "@/components/dashboard/ChartPanel";
import { Dial, DialLegend, type DialSegment } from "@/components/dashboard/chart-primitives";
import { useI18n, type Translate } from "@/contexts/I18nContext";
import type { StatsSummary } from "@/lib/api-client";

function segmentsFor(summary: StatsSummary, t: Translate): DialSegment[] {
  return [
    {
      key: "validated",
      label: t("precision.validatedLabel"),
      value: summary.analyses_validated,
      color: "var(--status-good)",
    },
    {
      key: "rejected",
      label: t("precision.rejectedLabel"),
      value: summary.analyses_rejected,
      color: "var(--status-critical)",
    },
  ];
}

/** How often the operator agreed with the AI's written analysis (FR-10). A closed ring
 * rather than the yield gauge's open arc, because this is a split of a reviewed set and not
 * a reading on a 0–100 scale — the two windows stay visually distinguishable at a glance.
 *
 * Stays empty until at least one analysis has been reviewed: `analysis_precision_rate` is
 * null in that case on purpose, so "nobody has given feedback yet" is never shown as 0%.
 */
export function AnalysisPrecisionChart({
  summary,
  expanded,
  isLoading,
  isError,
}: {
  summary: StatsSummary | undefined;
  expanded: boolean;
  isLoading: boolean;
  isError?: boolean;
}) {
  const { t } = useI18n();
  const reviewed = (summary?.analyses_validated ?? 0) + (summary?.analyses_rejected ?? 0);

  if (isLoading || isError) {
    return (
      <div className={expanded ? "h-[26rem]" : "h-52"}>
        <ChartPlaceholder
          isLoading={isLoading}
          isError={isError}
          emptyMessage={t("precision.empty")}
        />
      </div>
    );
  }

  // An unpowered gauge is still a gauge: the ring is drawn on its track with the needle at
  // rest, so the panel reads as an instrument waiting for its first reading rather than as a
  // blank quarter of the face. The rate stays a dash, never 0%, because nobody has reviewed.
  if (!summary || reviewed === 0) {
    return (
      <div
        className={`flex flex-col items-center justify-center gap-4 px-4 ${expanded ? "h-[26rem]" : "h-52"}`}
      >
        <Dial
          segments={[]}
          sweep={360}
          size={expanded ? 200 : 116}
          thickness={expanded ? 20 : 13}
          className="opacity-70"
          primary={
            <>
              <span
                className={`readout leading-none font-semibold text-muted-foreground/70 ${expanded ? "text-4xl" : "text-2xl"}`}
              >
                —
              </span>
              <span className="label-channel mt-2 text-muted-foreground/70">
                {t("precision.atRest")}
              </span>
            </>
          }
        />
        <p className="max-w-xs text-center text-[0.8125rem] leading-relaxed text-muted-foreground">
          {t("precision.emptyHint")}
        </p>
      </div>
    );
  }

  const segments = segmentsFor(summary, t);

  return (
    <div
      className={`flex items-center justify-center ${expanded ? "h-[26rem] gap-12" : "h-52 gap-6"}`}
      role="img"
      aria-label={t("precision.ariaLabel", {
        validated: summary.analyses_validated,
        rejected: summary.analyses_rejected,
      })}
    >
      <Dial
        segments={segments}
        sweep={360}
        size={expanded ? 300 : 148}
        thickness={expanded ? 26 : 13}
        primary={
          <>
            <span
              className={`readout font-semibold ${expanded ? "text-6xl" : "text-3xl"} leading-none`}
            >
              {(summary.analysis_precision_rate ?? 0).toFixed(1)}
              <span className="text-muted-foreground">%</span>
            </span>
            <span className="label-channel mt-2">{t("precision.validated")}</span>
          </>
        }
      />
      <DialLegend segments={segments} className={expanded ? "w-64" : "w-40"} />
    </div>
  );
}

export function AnalysisPrecisionDetail({ summary }: { summary: StatsSummary | undefined }) {
  const { t } = useI18n();
  const reviewed = (summary?.analyses_validated ?? 0) + (summary?.analyses_rejected ?? 0);
  if (!summary || reviewed === 0) return null;

  return (
    <ChartDataTable
      caption={t("precision.caption")}
      columns={[
        t("precision.column.decision"),
        t("chart.column.analyses"),
        t("chart.column.share"),
      ]}
      rows={[
        {
          key: "validated",
          color: "var(--status-good)",
          cells: [
            t("precision.validated"),
            summary.analyses_validated,
            `${((summary.analyses_validated / reviewed) * 100).toFixed(1)}%`,
          ],
        },
        {
          key: "rejected",
          color: "var(--status-critical)",
          cells: [
            t("precision.rejected"),
            summary.analyses_rejected,
            `${((summary.analyses_rejected / reviewed) * 100).toFixed(1)}%`,
          ],
        },
        { key: "reviewed", cells: [t("precision.row.reviewed"), reviewed, "100%"] },
      ]}
    />
  );
}
