"use client";

import { ChartDataTable, ChartPlaceholder } from "@/components/dashboard/ChartPanel";
import { Dial, DialLegend, type DialSegment } from "@/components/dashboard/chart-primitives";
import { useI18n, type Translate } from "@/contexts/I18nContext";
import type { StatsSummary } from "@/lib/api-client";

function segmentsFor(summary: StatsSummary, t: Translate): DialSegment[] {
  const withDefects = summary.total_with_defects;
  const clean = Math.max(0, summary.total_inspected - withDefects);
  return [
    { key: "clean", label: t("quality.cleanBoards"), value: clean, color: "var(--status-good)" },
    {
      key: "defects",
      label: t("quality.defectiveBoards"),
      value: withDefects,
      color: "var(--status-serious)",
    },
  ];
}

/** Yield, drawn as an open gauge (FE-02): the share of inspected boards that came back with
 * no reported defect. A dial rather than a bar because there is exactly one reading and a
 * fixed 0–100 scale — the arc's fill against its track is the whole message, and the split
 * underneath says how many boards each side of it represents.
 *
 * Colors come from the reserved status palette, never the categorical series hues: this is a
 * state (good / not good), not a defect identity.
 */
export function QualityRateChart({
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

  if (!summary || summary.total_inspected === 0) {
    return (
      <div className={expanded ? "h-[26rem]" : "h-52"}>
        <ChartPlaceholder
          isLoading={isLoading}
          isError={isError}
          emptyMessage={t("quality.empty")}
        />
      </div>
    );
  }

  const segments = segmentsFor(summary, t);

  return (
    <div
      className={`flex items-center justify-center ${expanded ? "h-[26rem] gap-12" : "h-52 gap-6"}`}
      role="img"
      aria-label={t("quality.ariaLabel", { rate: summary.quality_rate.toFixed(1) })}
    >
      <Dial
        segments={segments}
        sweep={252}
        size={expanded ? 320 : 160}
        thickness={expanded ? 26 : 13}
        primary={
          <>
            <span
              className={`readout font-semibold ${expanded ? "text-6xl" : "text-3xl"} leading-none`}
            >
              {summary.quality_rate.toFixed(1)}
              <span className="text-muted-foreground">%</span>
            </span>
            <span className="label-channel mt-2">{t("quality.defectFree")}</span>
          </>
        }
      />
      <DialLegend segments={segments} className={expanded ? "w-64" : "w-40"} />
    </div>
  );
}

export function QualityRateDetail({ summary }: { summary: StatsSummary | undefined }) {
  const { t } = useI18n();
  if (!summary || summary.total_inspected === 0) return null;
  const withDefects = summary.total_with_defects;
  const clean = Math.max(0, summary.total_inspected - withDefects);

  return (
    <ChartDataTable
      caption={t("quality.caption")}
      columns={[t("quality.column.outcome"), t("chart.column.boards"), t("chart.column.share")]}
      rows={[
        {
          key: "clean",
          color: "var(--status-good)",
          cells: [
            t("quality.defectFree"),
            clean,
            `${((clean / summary.total_inspected) * 100).toFixed(1)}%`,
          ],
        },
        {
          key: "defects",
          color: "var(--status-serious)",
          cells: [
            t("quality.row.withDefects"),
            withDefects,
            `${((withDefects / summary.total_inspected) * 100).toFixed(1)}%`,
          ],
        },
        {
          key: "total",
          cells: [t("quality.row.all"), summary.total_inspected, "100%"],
        },
        {
          key: "last24h",
          cells: [t("quality.row.last24h"), summary.last_24h_count, "—"],
        },
      ]}
    />
  );
}
