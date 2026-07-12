"use client";

import type { TooltipContentProps } from "recharts";
import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { StatsByDefectType } from "@/lib/api-client";
import { DEFECT_TYPE_COLOR, DEFECT_TYPE_LABEL, type DefectType } from "@/lib/chart-colors";

function DistributionTooltip({ active, payload }: TooltipContentProps) {
  if (!active || !payload || payload.length === 0) return null;
  const entry = payload[0];
  const defectType = entry.payload.defect_type as DefectType;

  return (
    <div className="rounded-md border border-border bg-popover px-3 py-2 text-xs shadow-md">
      <p className="flex items-center gap-1.5">
        <span
          aria-hidden="true"
          className="size-2 shrink-0 rounded-full"
          style={{ backgroundColor: entry.color }}
        />
        <span className="font-semibold tabular-nums text-popover-foreground">{entry.value}</span>
        <span className="text-muted-foreground">{DEFECT_TYPE_LABEL[defectType]}</span>
      </p>
    </div>
  );
}

/** Distribution-by-defect-type bar chart (FE-02) — one bar per fixed class, colored with the
 * same identity hues as `DefectBadge`/`DefectTrendChart` for cross-chart consistency. Every
 * bar carries its value at the tip so the count never lives only in the hover tooltip.
 */
export function DefectDistributionChart({
  data,
  isLoading,
  isError,
}: {
  data: StatsByDefectType | undefined;
  isLoading: boolean;
  isError?: boolean;
}) {
  const rows = (data?.counts ?? []).map((row) => ({
    ...row,
    label: DEFECT_TYPE_LABEL[row.defect_type],
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Distribution by defect type</CardTitle>
      </CardHeader>
      <CardContent>
        <div
          className="h-72"
          aria-busy={isLoading}
          role="img"
          aria-label="Bar chart of detection counts by defect class"
        >
          {rows.length === 0 ? (
            <p className="flex h-full items-center justify-center text-sm text-muted-foreground">
              {isError ? "Failed to load" : isLoading ? "Loading…" : "No detections yet"}
            </p>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={rows}
                layout="vertical"
                margin={{ top: 8, right: 24, bottom: 0, left: 0 }}
              >
                <XAxis type="number" allowDecimals={false} hide />
                <YAxis
                  type="category"
                  dataKey="label"
                  width={110}
                  stroke="var(--muted-foreground)"
                  tick={{ fontSize: 12 }}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip content={DistributionTooltip} cursor={{ fill: "var(--muted)" }} />
                <Bar dataKey="count" barSize={20} radius={[0, 4, 4, 0]}>
                  {rows.map((row) => (
                    <Cell key={row.defect_type} fill={DEFECT_TYPE_COLOR[row.defect_type]} />
                  ))}
                  <LabelList
                    dataKey="count"
                    position="right"
                    className="fill-foreground text-xs tabular-nums"
                  />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
