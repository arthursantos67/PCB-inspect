"use client";

import { useState } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";

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
  type DatasetExport,
  type DatasetExportFiltersInput,
  type DatasetExportStatus,
  downloadDatasetExport,
  listDatasetExports,
  requestDatasetExport,
} from "@/lib/api-client";
import { DEFECT_TYPES, DEFECT_TYPE_LABEL, type DefectType } from "@/lib/chart-colors";

const PAGE_SIZE = 20;

type ReviewStatusFilter = "confirmed" | "false_positive";

const REVIEW_STATUS_FILTERS: readonly ReviewStatusFilter[] = ["confirmed", "false_positive"];
const REVIEW_STATUS_FILTER_LABEL: Record<ReviewStatusFilter, string> = {
  confirmed: "Confirmed detections",
  false_positive: "False-positive corrections",
};

const STATUS_LABEL: Record<DatasetExportStatus, string> = {
  PENDING: "Generating…",
  COMPLETED: "Ready",
  FAILED: "Failed",
};

const STATUS_VARIANT: Record<DatasetExportStatus, "default" | "secondary" | "destructive" | "outline"> =
  {
    PENDING: "outline",
    COMPLETED: "default",
    FAILED: "destructive",
  };

function describeFilters(datasetExport: DatasetExport): string {
  const filters = datasetExport.filters ?? {};
  const parts = Object.entries(filters).filter(
    ([, value]) => value != null && value !== "" && !(Array.isArray(value) && value.length === 0)
  );
  if (parts.length === 0) return "Every reviewed detection";
  return parts
    .map(([key, value]) => `${key}=${Array.isArray(value) ? value.join(",") : value}`)
    .join(", ");
}

function describeManifest(datasetExport: DatasetExport): string {
  const manifest = datasetExport.manifest;
  if (!manifest) return "—";
  const versions = manifest.model_versions.map((v) => v.version).join(", ") || "manual only";
  return `${manifest.statistics.image_count} images, ${manifest.statistics.label_count} labels — ${versions}`;
}

function RequestDatasetExportForm({ onRequested }: { onRequested: () => void }) {
  const [defectTypes, setDefectTypes] = useState<DefectType[]>([]);
  const [reviewStatuses, setReviewStatuses] = useState<ReviewStatusFilter[]>([]);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function toggleDefectType(defectType: DefectType) {
    setDefectTypes((current) =>
      current.includes(defectType)
        ? current.filter((item) => item !== defectType)
        : [...current, defectType]
    );
  }

  function toggleReviewStatus(reviewStatus: ReviewStatusFilter) {
    setReviewStatuses((current) =>
      current.includes(reviewStatus)
        ? current.filter((item) => item !== reviewStatus)
        : [...current, reviewStatus]
    );
  }

  async function submit() {
    setError(null);
    setSubmitting(true);
    try {
      const filters: DatasetExportFiltersInput = {
        defect_type: defectTypes.length > 0 ? defectTypes : undefined,
        review_status: reviewStatuses.length > 0 ? reviewStatuses : undefined,
        date_from: dateFrom ? `${dateFrom}T00:00:00Z` : undefined,
        date_to: dateTo ? `${dateTo}T23:59:59Z` : undefined,
      };
      await requestDatasetExport(filters);
      setDefectTypes([]);
      setReviewStatuses([]);
      setDateFrom("");
      setDateTo("");
      onRequested();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to request this export.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Request a dataset export</CardTitle>
        <CardDescription>
          Packages confirmed detections, false-positive corrections, and manual annotations into
          a YOLO-format ZIP (FR-18) — generation runs in the background and appears below as
          &ldquo;Generating…&rdquo;.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <span id="export-defect-type-label" className="text-sm font-medium">
            Defect type
          </span>
          <div
            role="group"
            aria-labelledby="export-defect-type-label"
            className="flex flex-wrap gap-x-4 gap-y-2"
          >
            {DEFECT_TYPES.map((defectType) => (
              <label key={defectType} className="flex items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={defectTypes.includes(defectType)}
                  onChange={() => toggleDefectType(defectType)}
                />
                {DEFECT_TYPE_LABEL[defectType]}
              </label>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">No selection means every defect type.</p>
        </div>

        <div className="flex flex-col gap-1.5">
          <span id="export-review-status-label" className="text-sm font-medium">
            Review status
          </span>
          <div
            role="group"
            aria-labelledby="export-review-status-label"
            className="flex flex-wrap gap-x-4 gap-y-2"
          >
            {REVIEW_STATUS_FILTERS.map((reviewStatus) => (
              <label key={reviewStatus} className="flex items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={reviewStatuses.includes(reviewStatus)}
                  onChange={() => toggleReviewStatus(reviewStatus)}
                />
                {REVIEW_STATUS_FILTER_LABEL[reviewStatus]}
              </label>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            No selection means both confirmed detections and false-positive corrections
            (manual annotations are always included, pre-confirmed).
          </p>
        </div>

        <div className="grid max-w-md grid-cols-2 gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="export-date-from">From</Label>
            <Input
              id="export-date-from"
              type="date"
              value={dateFrom}
              onChange={(event) => setDateFrom(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="export-date-to">To</Label>
            <Input
              id="export-date-to"
              type="date"
              value={dateTo}
              onChange={(event) => setDateTo(event.target.value)}
            />
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Button size="sm" className="w-fit" disabled={submitting} onClick={() => void submit()}>
            Generate export
          </Button>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

function DatasetExportActionCell({ datasetExport }: { datasetExport: DatasetExport }) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (datasetExport.status === "PENDING") {
    return <span className="text-xs text-muted-foreground">Waiting…</span>;
  }

  if (datasetExport.status === "FAILED") {
    return (
      <span className="max-w-64 text-xs text-destructive">
        {datasetExport.error_message ?? "Generation failed."}
      </span>
    );
  }

  async function handleDownload() {
    setDownloading(true);
    setError(null);
    try {
      await downloadDatasetExport(datasetExport);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to download this export.");
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

export default function DatasetExportsPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);

  // Query key prefixed with "dataset-exports" — useEventStream (FE-09) invalidates that prefix
  // on every `dataset_export.completed`/`dataset_export.failed` SSE event.
  const listQuery = useQuery({
    queryKey: ["dataset-exports", "list", page],
    queryFn: () => listDatasetExports({ page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });

  const total = listQuery.data?.count ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  function handleRequested() {
    setPage(1);
    void queryClient.invalidateQueries({ queryKey: ["dataset-exports"] });
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold">Dataset export</h1>
        <p className="text-sm text-muted-foreground">
          Export reviewed detections as a labeled YOLO-format dataset (FR-18) — the input to
          retraining the model on real deployment-environment data.
        </p>
      </div>

      <RequestDatasetExportForm onRequested={handleRequested} />

      <Card>
        <CardHeader>
          <CardTitle>Generated exports{listQuery.isSuccess ? ` (${total})` : ""}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Filters</TableHead>
                <TableHead>Contents</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Requested</TableHead>
                <TableHead>Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(listQuery.data?.results ?? []).map((datasetExport) => (
                <TableRow key={datasetExport.id}>
                  <TableCell className="max-w-64 text-xs text-muted-foreground">
                    {describeFilters(datasetExport)}
                  </TableCell>
                  <TableCell className="max-w-72 text-xs text-muted-foreground">
                    {describeManifest(datasetExport)}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={STATUS_VARIANT[datasetExport.status]}
                      aria-live={datasetExport.status === "PENDING" ? "polite" : undefined}
                    >
                      {STATUS_LABEL[datasetExport.status]}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {new Date(datasetExport.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    <DatasetExportActionCell datasetExport={datasetExport} />
                  </TableCell>
                </TableRow>
              ))}
              {listQuery.isSuccess && total === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-sm text-muted-foreground">
                    No dataset exports generated yet.
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
