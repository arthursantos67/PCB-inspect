"use client";

import type { TooltipContentProps } from "recharts";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PeriodSelector } from "@/components/dashboard/PeriodSelector";
import type { StatsTrends, TrendPeriod } from "@/lib/api-client";
import { DEFECT_TYPES, DEFECT_TYPE_COLOR, DEFECT_TYPE_LABEL, type DefectType } from "@/lib/chart-colors";

function formatBucketLabel(bucket: string): string {
  return new Date(bucket).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function TrendTooltip({ active, payload, label }: TooltipContentProps) {
  if (!active || !payload || payload.length === 0) return null;
  const reported = payload.filter((entry) => typeof entry.value === "number" && entry.value > 0);

  return (
    <div className="rounded-md border border-border bg-popover px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-medium text-popover-foreground">{formatBucketLabel(String(label))}</p>
      {reported.length === 0 ? (
        <p className="text-muted-foreground">No reported defects</p>
      ) : (
        <ul className="space-y-1">
          {reported.map((entry) => (
            <li key={String(entry.dataKey)} className="flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className="h-0.5 w-3 shrink-0"
                style={{ backgroundColor: entry.color }}
              />
              <span className="font-semibold tabular-nums text-popover-foreground">
                {entry.value}
              </span>
              <span className="text-muted-foreground">
                {DEFECT_TYPE_LABEL[entry.dataKey as DefectType]}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Trend chart (FE-02): reported-defect counts over time, broken down by defect class, with
 * a 7d/30d/90d period selector. Six fixed-color series stay within the categorical soft cap
 * (dataviz skill) — identified by legend + tooltip rather than crowded end-labels.
 */
export function DefectTrendChart({
  data,
  period,
  onPeriodChange,
  isLoading,
  isError,
}: {
  data: StatsTrends | undefined;
  period: TrendPeriod;
  onPeriodChange: (period: TrendPeriod) => void;
  isLoading: boolean;
  isError?: boolean;
}) {
  const rows = (data?.points ?? []).map((point) => ({
    bucket: point.bucket,
    ...point.by_defect_type,
  }));

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
        <CardTitle>Defect trend</CardTitle>
        <PeriodSelector value={period} onChange={onPeriodChange} />
      </CardHeader>
      <CardContent>
        <div className="h-72" aria-busy={isLoading}>
          {rows.length === 0 ? (
            <p className="flex h-full items-center justify-center text-sm text-muted-foreground">
              {isError ? "Failed to load" : isLoading ? "Loading…" : "No data for this period yet"}
            </p>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--border)" />
                <XAxis
                  dataKey="bucket"
                  tickFormatter={formatBucketLabel}
                  stroke="var(--muted-foreground)"
                  tick={{ fontSize: 11 }}
                  tickLine={false}
                  axisLine={{ stroke: "var(--border)" }}
                  minTickGap={24}
                />
                <YAxis
                  allowDecimals={false}
                  stroke="var(--muted-foreground)"
                  tick={{ fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                  width={28}
                />
                <Tooltip content={TrendTooltip} cursor={{ stroke: "var(--border)" }} />
                <Legend
                  wrapperStyle={{ fontSize: 12 }}
                  formatter={(value: string) => (
                    <span className="text-muted-foreground">
                      {DEFECT_TYPE_LABEL[value as DefectType]}
                    </span>
                  )}
                />
                {DEFECT_TYPES.map((defectType) => (
                  <Line
                    key={defectType}
                    type="monotone"
                    dataKey={defectType}
                    name={defectType}
                    stroke={DEFECT_TYPE_COLOR[defectType]}
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
