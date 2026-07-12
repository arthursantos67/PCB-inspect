"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { DefectDistributionChart } from "@/components/dashboard/DefectDistributionChart";
import { DefectTrendChart } from "@/components/dashboard/DefectTrendChart";
import { InspectionTable } from "@/components/dashboard/InspectionTable";
import { StatCard, StatCardSkeleton } from "@/components/dashboard/StatCard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getStatsByDefectType,
  getStatsSummary,
  getStatsTrends,
  listInspections,
  type TrendPeriod,
} from "@/lib/api-client";

const RECENT_ANALYSES_PAGE_SIZE = 10;

export default function DashboardPage() {
  const [period, setPeriod] = useState<TrendPeriod>("30d");

  // Every query key here is prefixed with "stats" or "inspections" — useEventStream (FE-09)
  // already invalidates both prefixes on every SSE pipeline event, so the dashboard refreshes
  // live with no additional wiring (Issue 8).
  const summaryQuery = useQuery({ queryKey: ["stats", "summary"], queryFn: getStatsSummary });
  const trendsQuery = useQuery({
    queryKey: ["stats", "trends", period],
    queryFn: () => getStatsTrends(period),
  });
  const distributionQuery = useQuery({
    queryKey: ["stats", "by-defect-type"],
    queryFn: getStatsByDefectType,
  });
  const recentQuery = useQuery({
    queryKey: ["inspections", "recent"],
    queryFn: () => listInspections({ page_size: RECENT_ANALYSES_PAGE_SIZE, ordering: "-created_at" }),
  });

  const summary = summaryQuery.data;

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {summaryQuery.isPending ? (
          <>
            <StatCardSkeleton label="Total inspected" />
            <StatCardSkeleton label="Defects detected" />
            <StatCardSkeleton label="Quality rate" />
            <StatCardSkeleton label="Last 24h" />
          </>
        ) : (
          <>
            <StatCard
              label="Total inspected"
              value={summaryQuery.isError ? "—" : (summary?.total_inspected ?? 0).toLocaleString()}
              hint="Completed inspections"
            />
            <StatCard
              label="Defects detected"
              value={summaryQuery.isError ? "—" : (summary?.total_with_defects ?? 0).toLocaleString()}
              hint="Inspections with a reported defect"
            />
            <StatCard
              label="Quality rate"
              value={summaryQuery.isError ? "—" : `${(summary?.quality_rate ?? 0).toFixed(1)}%`}
              hint="Defect-free share of inspections"
            />
            <StatCard
              label="Last 24h"
              value={summaryQuery.isError ? "—" : (summary?.last_24h_count ?? 0).toLocaleString()}
              hint="Completed in the past 24 hours"
            />
          </>
        )}
      </div>

      <DefectTrendChart
        data={trendsQuery.data}
        period={period}
        onPeriodChange={setPeriod}
        isLoading={trendsQuery.isPending}
        isError={trendsQuery.isError}
      />

      <DefectDistributionChart
        data={distributionQuery.data}
        isLoading={distributionQuery.isPending}
        isError={distributionQuery.isError}
      />

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Recent analyses</CardTitle>
          <Link href="/inspections" className="text-sm text-primary hover:underline">
            View all
          </Link>
        </CardHeader>
        <CardContent>
          <InspectionTable
            items={recentQuery.data?.results ?? []}
            isLoading={recentQuery.isPending}
            isError={recentQuery.isError}
          />
        </CardContent>
      </Card>
    </div>
  );
}
