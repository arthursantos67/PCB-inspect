"use client";

import type { TooltipContentProps } from "recharts";
import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ChartDataTable, ChartPlaceholder } from "@/components/dashboard/ChartPanel";
import { TooltipRow, TooltipShell } from "@/components/dashboard/chart-primitives";
import { useI18n, type Translate } from "@/contexts/I18nContext";
import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
import type { StatsByDefectType } from "@/lib/api-client";
import { DEFECT_TYPE_COLOR, type DefectType } from "@/lib/chart-colors";

type Row = { defect_type: DefectType; count: number; label: string; share: number };

function DistributionTooltip({ active, payload }: TooltipContentProps) {
  const { t } = useI18n();
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0].payload as Row;

  return (
    <TooltipShell title={row.label}>
      <ul>
        <TooltipRow
          color={DEFECT_TYPE_COLOR[row.defect_type]}
          label={t("distribution.tooltip.detections")}
          value={row.count}
        />
        <TooltipRow label={t("distribution.tooltip.share")} value={row.share.toFixed(1)} suffix="%" />
      </ul>
    </TooltipShell>
  );
}

// The class label is baked into the row rather than looked up at render time: recharts uses it
// as the y-axis category key, so it has to be a plain string the chart can sort and match on.
function toRows(
  data: StatsByDefectType | undefined,
  hidden: ReadonlySet<DefectType>,
  t: Translate
): Row[] {
  const counts = (data?.counts ?? []).filter((row) => !hidden.has(row.defect_type));
  // Share is of the visible total, so muting classes in the key re-bases the percentages to
  // the subset the operator is actually looking at.
  const total = counts.reduce((sum, row) => sum + row.count, 0);
  return counts
    .map((row) => ({
      defect_type: row.defect_type,
      count: row.count,
      label: t(`defect.${row.defect_type}`),
      share: total > 0 ? (row.count / total) * 100 : 0,
    }))
    // Ranked, not enumerated: the question this chart answers is "which class dominates".
    .sort((a, b) => b.count - a.count);
}

/** Detections by defect class (FE-02), ranked. Colors are the same fixed identity hues the
 * trend lines and `DefectBadge` use, so a class is the same color everywhere it appears.
 * Every bar carries its count at the tip — the number never lives only in a tooltip.
 */
export function DefectDistributionChart({
  data,
  hidden,
  expanded,
  isLoading,
  isError,
}: {
  data: StatsByDefectType | undefined;
  hidden: ReadonlySet<DefectType>;
  expanded: boolean;
  isLoading: boolean;
  isError?: boolean;
}) {
  const prefersReducedMotion = usePrefersReducedMotion();
  const { t } = useI18n();
  const rows = toRows(data, hidden, t);
  const hasDetections = rows.some((row) => row.count > 0);

  return (
    <div
      className={expanded ? "h-[26rem]" : "h-52"}
      aria-busy={isLoading}
      role="img"
      aria-label={t("distribution.ariaLabel")}
    >
      {!hasDetections ? (
        <ChartPlaceholder
          isLoading={isLoading}
          isError={isError}
          emptyMessage={rows.length === 0 ? t("chart.allHidden") : t("distribution.empty")}
        />
      ) : (
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={rows}
            layout="vertical"
            barCategoryGap={expanded ? 14 : 6}
            margin={{ top: 4, right: 40, bottom: 4, left: 0 }}
          >
            <XAxis type="number" allowDecimals={false} hide />
            <YAxis
              type="category"
              dataKey="label"
              width={expanded ? 130 : 112}
              tick={{ fontSize: expanded ? 12 : 11, fill: "var(--foreground)" }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              content={DistributionTooltip}
              cursor={{ fill: "var(--accent)" }}
              animationDuration={prefersReducedMotion ? 0 : 120}
            />
            <Bar
              dataKey="count"
              barSize={expanded ? 22 : 14}
              radius={[0, 4, 4, 0]}
              // A class with no detections still gets a tick at the origin: "none recorded" is
              // a reading, and a row that draws nothing at all reads as missing data instead.
              minPointSize={(value) => (value === 0 ? 2 : 0)}
              isAnimationActive={!prefersReducedMotion}
              animationDuration={620}
              animationEasing="ease-out"
            >
              {rows.map((row) => (
                <Cell key={row.defect_type} fill={DEFECT_TYPE_COLOR[row.defect_type]} />
              ))}
              <LabelList
                dataKey="count"
                position="right"
                offset={8}
                className="fill-foreground"
                style={{
                  fontFamily: "var(--font-plex-mono)",
                  fontSize: expanded ? 12 : 11,
                  fontWeight: 600,
                }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

export function DefectDistributionDetail({
  data,
  hidden,
}: {
  data: StatsByDefectType | undefined;
  hidden: ReadonlySet<DefectType>;
}) {
  const { t } = useI18n();
  const rows = toRows(data, hidden, t);
  if (rows.length === 0) return null;

  return (
    <ChartDataTable
      caption={t("distribution.caption")}
      columns={[
        t("chart.column.defectClass"),
        t("chart.column.detections"),
        t("chart.column.share"),
      ]}
      rows={rows.map((row) => ({
        key: row.defect_type,
        color: DEFECT_TYPE_COLOR[row.defect_type],
        cells: [row.label, row.count, `${row.share.toFixed(1)}%`],
      }))}
    />
  );
}
