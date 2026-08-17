"use client";

import type { TooltipContentProps } from "recharts";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ChartDataTable, ChartPlaceholder } from "@/components/dashboard/ChartPanel";
import { TooltipRow, TooltipShell } from "@/components/dashboard/chart-primitives";
import { useI18n } from "@/contexts/I18nContext";
import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
import type { StatsTrends, TrendPeriod } from "@/lib/api-client";
import { DEFECT_TYPES, DEFECT_TYPE_COLOR, type DefectType } from "@/lib/chart-colors";
import { currentLocale } from "@/lib/i18n/language-store";

const AXIS_TICK = {
  fontSize: 11,
  fontFamily: "var(--font-plex-mono)",
  fill: "var(--muted-foreground)",
} as const;

function formatBucketLabel(bucket: string): string {
  return new Date(bucket).toLocaleDateString(currentLocale(), {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

function formatBucketLong(bucket: string): string {
  return new Date(bucket).toLocaleDateString(currentLocale(), {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** Only the classes that actually occurred on the hovered day, worst first: on a quiet day
 * that is one line, on a bad day it ranks the causes without the operator reading six rows
 * of zeroes.
 */
function TrendTooltip({ active, payload, label }: TooltipContentProps) {
  const { t } = useI18n();
  if (!active || !payload || payload.length === 0) return null;
  const reported = payload
    .filter((entry) => typeof entry.value === "number" && entry.value > 0)
    .sort((a, b) => Number(b.value) - Number(a.value));
  const total = reported.reduce((sum, entry) => sum + Number(entry.value), 0);

  return (
    <TooltipShell title={formatBucketLong(String(label))}>
      {reported.length === 0 ? (
        <p className="text-muted-foreground">{t("trend.noDefects")}</p>
      ) : (
        <>
          <ul>
            {reported.map((entry) => (
              <TooltipRow
                key={String(entry.dataKey)}
                color={entry.color}
                label={t(`defect.${entry.dataKey as DefectType}`)}
                value={entry.value as number}
              />
            ))}
          </ul>
          {reported.length > 1 && (
            <p className="mt-2 flex items-center justify-between border-t border-border pt-1.5">
              <span className="text-muted-foreground">{t("trend.allClasses")}</span>
              <span className="readout font-semibold">{total}</span>
            </p>
          )}
        </>
      )}
    </TooltipShell>
  );
}

function toRows(data: StatsTrends | undefined) {
  const zeroed = Object.fromEntries(DEFECT_TYPES.map((defectType) => [defectType, 0]));
  return (data?.points ?? []).map((point) => ({
    bucket: String(point.bucket),
    ...zeroed,
    ...point.by_defect_type,
  }));
}

/** Reported defects over time, split by class (FE-02). Six fixed-color lines stay inside the
 * categorical soft cap; identity comes from the shared class key rather than a legend
 * repeated in every panel, and a muted class is dropped from the plot entirely so the y-axis
 * rescales to what is left — that is what makes isolating one class useful.
 */
export function DefectTrendChart({
  data,
  hidden,
  expanded,
  isLoading,
  isError,
}: {
  data: StatsTrends | undefined;
  hidden: ReadonlySet<DefectType>;
  expanded: boolean;
  isLoading: boolean;
  isError?: boolean;
}) {
  const prefersReducedMotion = usePrefersReducedMotion();
  const { t } = useI18n();
  const rows = toRows(data);
  // A class with nothing in this window is still drawn — its absence is a reading — but it is
  // drawn back: six flat lines stacked on the baseline otherwise carry the same weight as the
  // one class that actually moved. Quiet ones render first so an active line sits above them.
  const visible = DEFECT_TYPES.filter((defectType) => !hidden.has(defectType))
    .map((defectType) => ({
      defectType,
      active: rows.some((row) => Number(row[defectType] ?? 0) > 0),
    }))
    .sort((a, b) => Number(a.active) - Number(b.active));

  return (
    <div
      className={expanded ? "h-[26rem]" : "h-52"}
      aria-busy={isLoading}
      role="img"
      aria-label={t("trend.ariaLabel")}
    >
      {rows.length === 0 || visible.length === 0 ? (
        <ChartPlaceholder
          isLoading={isLoading}
          isError={isError}
          emptyMessage={visible.length === 0 ? t("chart.allHidden") : t("trend.empty")}
        />
      ) : (
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="2 4" />
            <XAxis
              dataKey="bucket"
              tickFormatter={formatBucketLabel}
              tick={AXIS_TICK}
              tickLine={false}
              axisLine={{ stroke: "var(--border-strong)" }}
              tickMargin={8}
              minTickGap={expanded ? 32 : 40}
            />
            <YAxis
              allowDecimals={false}
              tick={AXIS_TICK}
              tickLine={false}
              axisLine={false}
              width={32}
            />
            <Tooltip
              content={TrendTooltip}
              cursor={{ stroke: "var(--border-strong)", strokeDasharray: "3 3" }}
              animationDuration={prefersReducedMotion ? 0 : 120}
            />
            {visible.map(({ defectType, active }) => (
              <Line
                key={defectType}
                type="monotone"
                dataKey={defectType}
                name={defectType}
                stroke={DEFECT_TYPE_COLOR[defectType]}
                strokeWidth={2}
                strokeOpacity={active ? 1 : 0.3}
                dot={false}
                // A 2px surface ring keeps the hovered point readable where lines overlap.
                activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }}
                isAnimationActive={!prefersReducedMotion}
                animationDuration={620}
                animationEasing="ease-out"
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

/** The plot's numbers, shown under the expanded read: per class, the period total and the
 * single worst day — the two questions a trend line prompts and cannot answer precisely.
 */
export function DefectTrendDetail({
  data,
  period,
  hidden,
}: {
  data: StatsTrends | undefined;
  period: TrendPeriod;
  hidden: ReadonlySet<DefectType>;
}) {
  const { t } = useI18n();
  const rows = toRows(data);
  if (rows.length === 0) return null;

  const summary = DEFECT_TYPES.filter((defectType) => !hidden.has(defectType)).map((defectType) => {
    let total = 0;
    let peak = { bucket: "", count: 0 };
    for (const row of rows) {
      const count = Number(row[defectType] ?? 0);
      total += count;
      if (count > peak.count) peak = { bucket: row.bucket, count };
    }
    return { defectType, total, peak };
  });

  return (
    <ChartDataTable
      caption={t("trend.caption", { period })}
      columns={[
        t("chart.column.defectClass"),
        t("chart.column.total"),
        t("trend.column.worstDay"),
        t("trend.column.thatDay"),
      ]}
      rows={summary.map((entry) => ({
        key: entry.defectType,
        color: DEFECT_TYPE_COLOR[entry.defectType],
        cells: [
          t(`defect.${entry.defectType}`),
          entry.total,
          entry.peak.count > 0 ? formatBucketLabel(entry.peak.bucket) : "—",
          entry.peak.count > 0 ? entry.peak.count : "—",
        ],
      }))}
    />
  );
}
