"use client";

import { Suspense, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { FilterBar } from "@/components/filters/FilterBar";
import { InspectionTable } from "@/components/dashboard/InspectionTable";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { listInspections } from "@/lib/api-client";
import {
  filtersFromSearchParams,
  filtersToSearchParams,
  type InspectionFilterValues,
} from "@/lib/inspection-filters";

const PAGE_SIZE = 20;

function InspectionsSearchPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const filters = useMemo(() => filtersFromSearchParams(searchParams), [searchParams]);
  const page = Math.max(1, Number.parseInt(searchParams.get("page") ?? "1", 10) || 1);

  function navigate(nextFilters: InspectionFilterValues, nextPage: number) {
    const params = filtersToSearchParams(nextFilters);
    if (nextPage > 1) params.set("page", String(nextPage));
    const query = params.toString();
    router.push(query ? `${pathname}?${query}` : pathname);
  }

  // Query key mirrors the URL exactly, so a shared/bookmarked link and a fresh navigation
  // hit the same cache entry. Prefixed with "inspections" — useEventStream (FE-09) already
  // invalidates that prefix on every SSE pipeline event, so results stay live.
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
  });

  const total = listQuery.data?.count ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold">Inspections</h1>
        <p className="text-sm text-muted-foreground">Search and filter historical inspections.</p>
      </div>

      <FilterBar value={filters} onChange={(next) => navigate(next, 1)} />

      <Card>
        <CardHeader>
          <CardTitle>Results{listQuery.isSuccess ? ` (${total})` : ""}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <InspectionTable
            items={listQuery.data?.results ?? []}
            isLoading={listQuery.isPending}
            isError={listQuery.isError}
            emptyMessage="No inspections match these filters. Try adjusting or clearing them."
          />

          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">
                Page {page} of {totalPages}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => navigate(filters, page - 1)}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => navigate(filters, page + 1)}
                >
                  Next
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
