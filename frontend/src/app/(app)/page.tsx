"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";

import { AlertsBanner } from "@/components/dashboard/AlertsBanner";
import {
  AnalysisPrecisionChart,
  AnalysisPrecisionDetail,
} from "@/components/dashboard/AnalysisPrecisionChart";
import { ChartGrid, ChartPanel } from "@/components/dashboard/ChartPanel";
import { DefectClassKey } from "@/components/dashboard/DefectClassKey";
import {
  DefectDistributionChart,
  DefectDistributionDetail,
} from "@/components/dashboard/DefectDistributionChart";
import { DefectTrendChart, DefectTrendDetail } from "@/components/dashboard/DefectTrendChart";
import { Metric, MetricSkeleton, MetricStrip } from "@/components/dashboard/MetricStrip";
import { PeriodSelector } from "@/components/dashboard/PeriodSelector";
import { QualityRateChart, QualityRateDetail } from "@/components/dashboard/QualityRateChart";
import { RecentBatchesTable } from "@/components/dashboard/RecentBatchesTable";
import { PageHeader } from "@/components/layout/PageHeader";
import { useI18n } from "@/contexts/I18nContext";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getRecentBatches,
  getStatsByDefectType,
  getStatsSummary,
  getStatsTrends,
  type TrendPeriod,
} from "@/lib/api-client";
import type { DefectType } from "@/lib/chart-colors";

const RECENT_BATCHES_LIMIT = 10;

export default function DashboardPage() {
  const { t } = useI18n();
  const [period, setPeriod] = useState<TrendPeriod>("30d");
  // Muting a class is a reading preference, not a filter on the data: it is held here so the
  // trend and the distribution stay in agreement about which classes are on screen.
  const [hiddenTypes, setHiddenTypes] = useState<ReadonlySet<DefectType>>(new Set());

  const toggleType = useCallback((defectType: DefectType) => {
    setHiddenTypes((current) => {
      const next = new Set(current);
      if (!next.delete(defectType)) next.add(defectType);
      return next;
    });
  }, []);

  const resetTypes = useCallback(() => setHiddenTypes(new Set()), []);

  // Every query key here is prefixed with "stats" — useEventStream (FE-09) already
  // invalidates that prefix on every SSE pipeline event, so the dashboard refreshes live
  // with no additional wiring (Issue 8).
  const summaryQuery = useQuery({ queryKey: ["stats", "summary"], queryFn: getStatsSummary });
  const trendsQuery = useQuery({
    queryKey: ["stats", "trends", period],
    queryFn: () => getStatsTrends(period),
  });
  const distributionQuery = useQuery({
    queryKey: ["stats", "by-defect-type"],
    queryFn: getStatsByDefectType,
  });
  const recentBatchesQuery = useQuery({
    queryKey: ["stats", "recent-batches"],
    queryFn: () => getRecentBatches(RECENT_BATCHES_LIMIT),
  });

  const summary = summaryQuery.data;
  const failed = summaryQuery.isError;
  const number = (value: number | undefined) =>
    failed ? "—" : (value ?? 0).toLocaleString();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow={t("dashboard.eyebrow")}
        title={t("dashboard.title")}
        description={t("dashboard.description")}
      />

      <AlertsBanner />

      <MetricStrip>
        {summaryQuery.isPending ? (
          <>
            <MetricSkeleton label={t("dashboard.metric.inspected")} />
            <MetricSkeleton label={t("dashboard.metric.withDefects")} />
            <MetricSkeleton label={t("dashboard.metric.detected")} />
            <MetricSkeleton label={t("dashboard.metric.last24h")} />
          </>
        ) : (
          <>
            <Metric
              label={t("dashboard.metric.inspected")}
              value={number(summary?.total_inspected)}
              hint={t("dashboard.metric.inspectedHint")}
            />
            {/* Counts inspected boards carrying at least one reported defect, not individual
                detections: one board with four defects counts once here. */}
            <Metric
              label={t("dashboard.metric.withDefects")}
              value={number(summary?.total_with_defects)}
              tone={(summary?.total_with_defects ?? 0) > 0 ? "attention" : "default"}
              hint={t("dashboard.metric.withDefectsHint")}
            />
            <Metric
              label={t("dashboard.metric.detected")}
              value={
                distributionQuery.isError ? "—" : (distributionQuery.data?.total ?? 0).toLocaleString()
              }
              hint={t("dashboard.metric.detectedHint")}
            />
            <Metric
              label={t("dashboard.metric.last24h")}
              value={number(summary?.last_24h_count)}
              hint={t("dashboard.metric.last24hHint")}
            />
          </>
        )}
      </MetricStrip>

      <ChartGrid
        footer={
          <DefectClassKey hidden={hiddenTypes} onToggle={toggleType} onReset={resetTypes} />
        }
      >
        <ChartPanel
          channel={t("dashboard.trend.channel")}
          title={t("dashboard.trend.title")}
          description={t("dashboard.trend.description")}
          toolbar={<PeriodSelector value={period} onChange={setPeriod} />}
          detail={
            <DefectTrendDetail data={trendsQuery.data} period={period} hidden={hiddenTypes} />
          }
        >
          {(expanded) => (
            <DefectTrendChart
              data={trendsQuery.data}
              hidden={hiddenTypes}
              expanded={expanded}
              isLoading={trendsQuery.isPending}
              isError={trendsQuery.isError}
            />
          )}
        </ChartPanel>

        <ChartPanel
          channel={t("dashboard.distribution.channel")}
          title={t("dashboard.distribution.title")}
          description={t("dashboard.distribution.description")}
          headline={
            distributionQuery.data ? (
              <span className="readout text-[0.8125rem] font-semibold">
                {distributionQuery.data.total.toLocaleString()}
                <span className="ml-1.5 font-sans text-[0.6875rem] font-normal text-muted-foreground">
                  {t("dashboard.distribution.detections")}
                </span>
              </span>
            ) : null
          }
          detail={
            <DefectDistributionDetail data={distributionQuery.data} hidden={hiddenTypes} />
          }
        >
          {(expanded) => (
            <DefectDistributionChart
              data={distributionQuery.data}
              hidden={hiddenTypes}
              expanded={expanded}
              isLoading={distributionQuery.isPending}
              isError={distributionQuery.isError}
            />
          )}
        </ChartPanel>

        <ChartPanel
          channel={t("dashboard.quality.channel")}
          title={t("dashboard.quality.title")}
          description={t("dashboard.quality.description")}
          detail={<QualityRateDetail summary={summary} />}
        >
          {(expanded) => (
            <QualityRateChart
              summary={summary}
              expanded={expanded}
              isLoading={summaryQuery.isPending}
              isError={summaryQuery.isError}
            />
          )}
        </ChartPanel>

        <ChartPanel
          channel={t("dashboard.precision.channel")}
          title={t("dashboard.precision.title")}
          description={t("dashboard.precision.description")}
          detail={<AnalysisPrecisionDetail summary={summary} />}
        >
          {(expanded) => (
            <AnalysisPrecisionChart
              summary={summary}
              expanded={expanded}
              isLoading={summaryQuery.isPending}
              isError={summaryQuery.isError}
            />
          )}
        </ChartPanel>
      </ChartGrid>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>{t("dashboard.recentBatches")}</CardTitle>
          <Link
            href="/inspections"
            className="inline-flex items-center gap-1 text-[0.8125rem] text-brand-ink transition-colors hover:text-foreground"
          >
            {t("dashboard.allInspections")}
            <ArrowRight className="size-3.5" />
          </Link>
        </CardHeader>
        <CardContent>
          <RecentBatchesTable
            items={recentBatchesQuery.data?.results ?? []}
            isLoading={recentBatchesQuery.isPending}
            isError={recentBatchesQuery.isError}
          />
        </CardContent>
      </Card>
    </div>
  );
}
