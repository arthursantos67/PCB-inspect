"use client";

import { Suspense, useMemo } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";

import { FilterBar } from "@/components/filters/FilterBar";
import { PageHeader } from "@/components/layout/PageHeader";
import { BatchTable } from "@/components/dashboard/BatchTable";
import { InspectionTable } from "@/components/dashboard/InspectionTable";
import { SeverityBadge } from "@/components/dashboard/SeverityBadge";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/contexts/I18nContext";
import { getBatch, listBatches, listInspections } from "@/lib/api-client";
import {
  filtersFromSearchParams,
  filtersToSearchParams,
  type InspectionFilterValues,
} from "@/lib/inspection-filters";

const PAGE_SIZE = 20;

/** Boards arrive in batches, so the screen starts at the batch level and drills into a
 * batch's boards. The board list itself, its filters and its
 * rows are unchanged.
 *
 * Which level is shown comes from the URL, so both are linkable: `view=boards` is what a
 * batch row links to, and a link carrying only `batch_number` (what the dashboard's recent
 * batches table used to emit, and any bookmark made from it) also opens the boards, since
 * naming a single batch is what the operator meant. The batch list's own search box always
 * pins `view=batches` so typing in it never flips the level under the operator.
 */
function InspectionsSearchPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { t } = useI18n();

  const filters = useMemo(() => filtersFromSearchParams(searchParams), [searchParams]);
  const page = Math.max(1, Number.parseInt(searchParams.get("page") ?? "1", 10) || 1);
  const view =
    searchParams.get("view") ?? (filters.batch_number ? "boards" : "batches");
  const showingBoards = view === "boards";

  function navigate(nextFilters: InspectionFilterValues, nextPage: number) {
    const params = filtersToSearchParams(nextFilters);
    // No batch named means nothing to drill into, so the screen falls back to the batch list:
    // that is what clearing the filters from inside a batch does.
    if (nextFilters.batch_number) params.set("view", showingBoards ? "boards" : "batches");
    if (nextPage > 1) params.set("page", String(nextPage));
    const query = params.toString();
    router.push(query ? `${pathname}?${query}` : pathname);
  }

  // Query keys mirror the URL exactly, so a shared/bookmarked link and a fresh navigation
  // hit the same cache entry. Both are prefixed with "inspections" — useEventStream (FE-09)
  // already invalidates that prefix on every SSE pipeline event, so results stay live.
  const batchesQuery = useQuery({
    queryKey: ["inspections", "batches", filters.batch_number, filters.date_from, filters.date_to, page],
    queryFn: () =>
      listBatches({
        page,
        page_size: PAGE_SIZE,
        batch_number: filters.batch_number || undefined,
        date_from: filters.date_from ? `${filters.date_from}T00:00:00Z` : undefined,
        date_to: filters.date_to ? `${filters.date_to}T23:59:59Z` : undefined,
      }),
    placeholderData: keepPreviousData,
    enabled: !showingBoards,
  });

  const listQuery = useQuery({
    queryKey: ["inspections", "search", filters, page],
    queryFn: () =>
      listInspections({
        page,
        page_size: PAGE_SIZE,
        defect_type: filters.defect_type.length > 0 ? filters.defect_type : undefined,
        batch_number: filters.batch_number || undefined,
        board_number: filters.board_number || undefined,
        status: filters.status || undefined,
        severity: filters.severity || undefined,
        review_status: filters.review_status || undefined,
        disposition: filters.disposition || undefined,
        // Dates are UTC (PRD section 11.1) — the date-only picker value is treated as a UTC
        // calendar day, not the browser's local midnight, so filtering stays correct
        // regardless of the operator's timezone.
        date_from: filters.date_from ? `${filters.date_from}T00:00:00Z` : undefined,
        date_to: filters.date_to ? `${filters.date_to}T23:59:59Z` : undefined,
      }),
    placeholderData: keepPreviousData,
    enabled: showingBoards,
  });

  // Summary strip above the drilled-into batch's boards. Best-effort: a free-text batch
  // filter that matches no batch exactly just leaves it out.
  const batchQuery = useQuery({
    queryKey: ["inspections", "batch", filters.batch_number],
    queryFn: () => getBatch(filters.batch_number),
    enabled: showingBoards && filters.batch_number.length > 0,
    retry: false,
  });

  const activeQuery = showingBoards ? listQuery : batchesQuery;
  const total = activeQuery.data?.count ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const batch = batchQuery.data;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow={t(showingBoards ? "inspections.eyebrow.batch" : "inspections.eyebrow.history")}
        title={
          showingBoards
            ? filters.batch_number
              ? t("inspections.titleBatch", { batch: filters.batch_number })
              : t("inspections.titleBoards")
            : t("inspections.title")
        }
        description={t(
          showingBoards ? "inspections.descriptionBoards" : "inspections.descriptionBatches"
        )}
      >
        {showingBoards && (
          <Link
            href="/inspections"
            className="inline-flex w-fit items-center gap-1.5 text-[0.8125rem] text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="size-3.5" />
            {t("inspections.allBatches")}
          </Link>
        )}
      </PageHeader>

      {/* The batch's own numbers, read as a strip before the board list rather than as a
          sentence: the operator is checking whether this batch is in trouble, not reading. */}
      {showingBoards && batch && (
        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border shadow-panel sm:grid-cols-3 lg:grid-cols-5">
          <div className="bg-card px-4 py-3">
            <dt className="label-channel">{t("inspections.summary.inspected")}</dt>
            <dd className="readout mt-1.5 text-base leading-none font-semibold">
              {batch.completed_count}
              <span className="ml-1 text-xs font-normal text-muted-foreground">
                {t("common.ofTotal", { total: batch.board_count })}
              </span>
            </dd>
          </div>
          <div className="bg-card px-4 py-3">
            <dt className="label-channel">{t("inspections.summary.withDefects")}</dt>
            <dd
              className={`readout mt-1.5 text-base leading-none font-semibold ${
                batch.boards_with_defects > 0 ? "text-status-serious" : ""
              }`}
            >
              {batch.boards_with_defects}
              <span className="ml-1 text-xs font-normal text-muted-foreground">
                {Math.round(batch.defect_rate * 100)}%
              </span>
            </dd>
          </div>
          <div className="bg-card px-4 py-3">
            <dt className="label-channel">{t("inspections.summary.defects")}</dt>
            <dd className="readout mt-1.5 text-base leading-none font-semibold">
              {batch.defect_count}
            </dd>
          </div>
          <div className="bg-card px-4 py-3">
            <dt className="label-channel">{t("inspections.summary.severity")}</dt>
            <dd className="mt-1.5">
              {batch.severity ? (
                <SeverityBadge severity={batch.severity} />
              ) : (
                <span className="text-sm text-muted-foreground">—</span>
              )}
            </dd>
          </div>
          <div className="bg-card px-4 py-3">
            <dt className="label-channel">{t("inspections.summary.status")}</dt>
            <dd className="mt-1.5">
              <StatusBadge status={batch.status} />
            </dd>
          </div>
        </dl>
      )}

      <FilterBar
        value={filters}
        onChange={(next) => navigate(next, 1)}
        mode={showingBoards ? "boards" : "batches"}
      />

      <Card>
        <CardHeader>
          <CardTitle>
            {t(showingBoards ? "inspections.cardBoards" : "inspections.cardBatches")}
            {activeQuery.isSuccess ? ` (${total})` : ""}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {showingBoards ? (
            <InspectionTable
              items={listQuery.data?.results ?? []}
              isLoading={listQuery.isPending}
              isError={listQuery.isError}
              emptyMessage={t("inspections.noBoardsMatch")}
            />
          ) : (
            <BatchTable
              items={batchesQuery.data?.results ?? []}
              isLoading={batchesQuery.isPending}
              isError={batchesQuery.isError}
              emptyMessage={t("inspections.noBatchesMatch")}
            />
          )}

          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">
                {t("common.pageOf", { page, total: totalPages })}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => navigate(filters, page - 1)}
                >
                  {t("common.previous")}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => navigate(filters, page + 1)}
                >
                  {t("common.next")}
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function InspectionsPage() {
  return (
    <Suspense>
      <InspectionsSearchPage />
    </Suspense>
  );
}
