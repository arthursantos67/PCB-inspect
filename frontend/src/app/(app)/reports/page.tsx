"use client";

import { useState } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";

import { FilterBar } from "@/components/filters/FilterBar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  ApiError,
  downloadReport,
  listReports,
  requestReport,
  type Report,
  type ReportFormat,
  type ReportStatus,
  type ReportType,
} from "@/lib/api-client";
import {
  EMPTY_INSPECTION_FILTERS,
  type InspectionFilterValues,
} from "@/lib/inspection-filters";

const PAGE_SIZE = 20;

const REPORT_TYPES: readonly ReportType[] = ["individual", "consolidated", "executive"];

const REPORT_TYPE_LABEL: Record<ReportType, string> = {
  individual: "Individual",
  consolidated: "Consolidated",
  executive: "Executive summary",
};

const FORMATS_BY_TYPE: Record<ReportType, readonly ReportFormat[]> = {
  individual: ["pdf"],
  consolidated: ["csv", "xlsx", "pdf"],
  executive: ["pdf"],
};

const STATUS_LABEL: Record<ReportStatus, string> = {
  PENDING: "Generating…",
  COMPLETED: "Ready",
  FAILED: "Failed",
};

const STATUS_VARIANT: Record<ReportStatus, "default" | "secondary" | "destructive" | "outline"> =
  {
    PENDING: "outline",
    COMPLETED: "default",
    FAILED: "destructive",
  };

const SELECT_CLASS =
  "h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

function describeFilters(report: Report): string {
  const filters = report.filters ?? {};

  if (report.type === "individual") {
    const inspectionId = filters.inspection_id;
    return typeof inspectionId === "string" ? `Inspection ${inspectionId.slice(0, 8)}…` : "—";
  }

  if (report.type === "executive") {
    const from = typeof filters.date_from === "string" ? filters.date_from : null;
    const to = typeof filters.date_to === "string" ? filters.date_to : null;
    if (!from && !to) return "All time";
    return `${from ? new Date(from).toLocaleDateString() : "earliest"} – ${
      to ? new Date(to).toLocaleDateString() : "latest"
    }`;
  }

  const parts = Object.entries(filters).filter(
    ([, value]) => value != null && value !== "" && !(Array.isArray(value) && value.length === 0)
  );
  if (parts.length === 0) return "All inspections";
  return parts
    .map(([key, value]) => `${key}=${Array.isArray(value) ? value.join(",") : value}`)
    .join(", ");
}

function RequestReportForm({ onRequested }: { onRequested: () => void }) {
  const [type, setType] = useState<ReportType>("consolidated");
  const [format, setFormat] = useState<ReportFormat>("csv");
  const [inspectionId, setInspectionId] = useState("");
  const [filters, setFilters] = useState<InspectionFilterValues>(EMPTY_INSPECTION_FILTERS);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function changeType(next: ReportType) {
    setType(next);
    setFormat(FORMATS_BY_TYPE[next][0]);
    setError(null);
  }

  async function submit() {
    setError(null);

    if (type === "individual" && !inspectionId.trim()) {
      setError("Enter the inspection ID to report on.");
      return;
    }

    setSubmitting(true);
    try {
      if (type === "individual") {
        await requestReport({
          type: "individual",
          format: "pdf",
          inspection_id: inspectionId.trim(),
        });
      } else if (type === "consolidated") {
        await requestReport({
          type: "consolidated",
          format,
          filters: {
            defect_type: filters.defect_type.length > 0 ? filters.defect_type : undefined,
            batch_number: filters.batch_number || undefined,
            board_number: filters.board_number || undefined,
            status: filters.status || undefined,
            severity: filters.severity || undefined,
            review_status: filters.review_status || undefined,
            disposition: filters.disposition || undefined,
            date_from: filters.date_from ? `${filters.date_from}T00:00:00Z` : undefined,
            date_to: filters.date_to ? `${filters.date_to}T23:59:59Z` : undefined,
          },
        });
      } else {
        await requestReport({
          type: "executive",
          format: "pdf",
          date_from: dateFrom ? `${dateFrom}T00:00:00Z` : undefined,
          date_to: dateTo ? `${dateTo}T23:59:59Z` : undefined,
        });
      }
      setInspectionId("");
      setFilters(EMPTY_INSPECTION_FILTERS);
      setDateFrom("");
      setDateTo("");
      onRequested();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to request this report.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Request a report</CardTitle>
        <CardDescription>
          Generation runs in the background (FR-11) — the new report appears below as
          &ldquo;Generating…&rdquo; and updates automatically once it&apos;s ready.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid max-w-2xl grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="report-type">Report type</Label>
            <select
              id="report-type"
              className={SELECT_CLASS}
              value={type}
              onChange={(event) => changeType(event.target.value as ReportType)}
            >
              {REPORT_TYPES.map((value) => (
                <option key={value} value={value}>
                  {REPORT_TYPE_LABEL[value]}
                </option>
              ))}
            </select>
          </div>
          {type === "consolidated" && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="report-format">Format</Label>
              <select
                id="report-format"
                className={SELECT_CLASS}
                value={format}
                onChange={(event) => setFormat(event.target.value as ReportFormat)}
              >
                {FORMATS_BY_TYPE.consolidated.map((value) => (
                  <option key={value} value={value}>
                    {value.toUpperCase()}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {type === "individual" && (
          <div className="flex max-w-md flex-col gap-1.5">
            <Label htmlFor="report-inspection-id">Inspection ID</Label>
            <Input
              id="report-inspection-id"
              className="font-mono text-xs"
              placeholder="e.g. 9f6a1c2e-1234-4a5b-8c9d-0123456789ab"
              value={inspectionId}
              onChange={(event) => setInspectionId(event.target.value)}
            />
          </div>
        )}

        {type === "consolidated" && <FilterBar value={filters} onChange={setFilters} />}

        {type === "executive" && (
          <div className="grid max-w-md grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="report-date-from">From</Label>
              <Input
                id="report-date-from"
                type="date"
                value={dateFrom}
                onChange={(event) => setDateFrom(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="report-date-to">To</Label>
              <Input
                id="report-date-to"
                type="date"
                value={dateTo}
                onChange={(event) => setDateTo(event.target.value)}
              />
            </div>
          </div>
        )}

        <div className="flex items-center gap-3">
          <Button size="sm" className="w-fit" disabled={submitting} onClick={() => void submit()}>
            Generate report
          </Button>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

function ReportActionCell({ report }: { report: Report }) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (report.status === "PENDING") {
    return <span className="text-xs text-muted-foreground">Waiting…</span>;
  }

  if (report.status === "FAILED") {
    return (
      <span className="max-w-64 text-xs text-destructive">
        {report.error_message ?? "Generation failed."}
      </span>
    );
  }

  async function handleDownload() {
    setDownloading(true);
    setError(null);
    try {
      await downloadReport(report);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to download this report.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <Button
        size="sm"
        variant="outline"
        disabled={downloading}
        onClick={() => void handleDownload()}
      >
        Download
      </Button>
      {error && <span className="text-xs text-destructive">{error}</span>}
    </div>
  );
}

export default function ReportsPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);

  // Query key prefixed with "reports" — useEventStream (FE-09) invalidates that prefix on
  // every `report.completed`/`report.failed` SSE event, so status updates without a refresh.
  const listQuery = useQuery({
    queryKey: ["reports", "list", page],
    queryFn: () => listReports({ page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });

  const total = listQuery.data?.count ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  function handleRequested() {
    setPage(1);
    void queryClient.invalidateQueries({ queryKey: ["reports"] });
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold">Reports</h1>
        <p className="text-sm text-muted-foreground">
          Generate individual, consolidated, and executive summary reports, then find them here
          again later.
        </p>
      </div>

      <RequestReportForm onRequested={handleRequested} />

      <Card>
        <CardHeader>
          <CardTitle>Generated reports{listQuery.isSuccess ? ` (${total})` : ""}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Type</TableHead>
                <TableHead>Format</TableHead>
                <TableHead>Details</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Requested</TableHead>
                <TableHead>Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(listQuery.data?.results ?? []).map((report) => (
                <TableRow key={report.id}>
                  <TableCell className="font-medium">{REPORT_TYPE_LABEL[report.type]}</TableCell>
                  <TableCell className="uppercase">{report.format}</TableCell>
                  <TableCell className="max-w-64 text-xs text-muted-foreground">
                    {describeFilters(report)}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={STATUS_VARIANT[report.status]}
                      aria-live={report.status === "PENDING" ? "polite" : undefined}
                    >
                      {STATUS_LABEL[report.status]}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {new Date(report.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    <ReportActionCell report={report} />
                  </TableCell>
                </TableRow>
              ))}
              {listQuery.isSuccess && total === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-sm text-muted-foreground">
                    No reports generated yet.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>

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
                  onClick={() => setPage((current) => current - 1)}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((current) => current + 1)}
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
