"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";

import { FilterBar } from "@/components/filters/FilterBar";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LampChip, type LampTone } from "@/components/ui/lamp-chip";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useI18n, type Translate } from "@/contexts/I18nContext";
import {
  ApiError,
  downloadReport,
  listBatches,
  listInspections,
  listReports,
  requestReport,
  type InspectionListItem,
  type Report,
  type ReportFormat,
  type ReportLanguage,
  type ReportStatus,
  type ReportType,
} from "@/lib/api-client";
import { formatDate, formatTimestamp } from "@/lib/format";
import {
  EMPTY_INSPECTION_FILTERS,
  type InspectionFilterValues,
} from "@/lib/inspection-filters";

const PAGE_SIZE = 20;

// One page each, sized to cover a realistic shop floor without paginating a form control.
const BATCH_OPTIONS_PAGE_SIZE = 100;
const BOARD_OPTIONS_PAGE_SIZE = 200;

// How long the "Downloaded" confirmation stays up before the button goes back to idle.
const DOWNLOAD_CONFIRMATION_MS = 4000;

const REPORT_TYPES: readonly ReportType[] = ["individual", "consolidated", "executive"];

const FORMATS_BY_TYPE: Record<ReportType, readonly ReportFormat[]> = {
  individual: ["pdf", "csv", "xlsx"],
  consolidated: ["pdf", "csv", "xlsx"],
  executive: ["pdf"],
};

const LANGUAGES: readonly ReportLanguage[] = ["en", "pt"];

/** Same lamp chip as a board's status (StatusBadge): a report is either still running,
 * finished or failed, and an operator scanning this column should read it exactly the way
 * they read the inspections list, not as a solid dark chip that outweighs the row.
 */
const STATUS_LAMP: Record<ReportStatus, { tone: LampTone; pulse?: boolean }> = {
  PENDING: { tone: "neutral", pulse: true },
  COMPLETED: { tone: "good" },
  FAILED: { tone: "critical" },
};

function ReportStatusChip({ status }: { status: ReportStatus }) {
  const { t } = useI18n();
  return (
    <LampChip {...STATUS_LAMP[status]} aria-live={status === "PENDING" ? "polite" : undefined}>
      {t(`reports.status.${status}`)}
    </LampChip>
  );
}

// Shared control shell (globals.css) so the report options sit on the same baseline grid as
// the filter bar below them.
const SELECT_CLASS = "control";

function boardLabel(inspection: InspectionListItem, t: Translate): string {
  return inspection.board_number ?? t("reports.unnamedBoard", { id: inspection.id.slice(0, 8) });
}

// The filter keys the API can return in a report's `filters`. Anything outside this set is a
// key this build doesn't know, and falls back to its own name with the underscores removed.
const FILTER_KEYS = [
  "batch_number",
  "board_number",
  "status",
  "severity",
  "review_status",
  "disposition",
  "defect_types",
  "date_from",
  "date_to",
  "inspection_ids",
] as const;

type FilterKey = (typeof FILTER_KEYS)[number];

function filterLabel(key: string, t: Translate): string {
  return FILTER_KEYS.includes(key as FilterKey)
    ? t(`reports.filter.${key as FilterKey}`)
    : key.replace(/_/g, " ");
}

function describeFilters(report: Report, t: Translate): string {
  const filters = report.filters ?? {};

  if (report.type === "individual") {
    const inspectionId = filters.inspection_id;
    return typeof inspectionId === "string"
      ? t("reports.detail.inspection", { id: inspectionId.slice(0, 8) })
      : "-";
  }

  if (report.type === "executive") {
    const from = typeof filters.date_from === "string" ? filters.date_from : null;
    const to = typeof filters.date_to === "string" ? filters.date_to : null;
    if (!from && !to) return t("reports.detail.allTime");
    return t("reports.detail.range", {
      from: from ? formatDate(from) : t("reports.detail.earliest"),
      to: to ? formatDate(to) : t("reports.detail.latest"),
    });
  }

  // `language` is reported in its own column, so it is not repeated in the filter summary.
  const parts = Object.entries(filters).filter(
    ([key, value]) =>
      key !== "language" &&
      value != null &&
      value !== "" &&
      !(Array.isArray(value) && value.length === 0)
  );
  if (parts.length === 0) return t("reports.detail.allInspections");
  // Named in the operator's words, not the query string's: this column is read to recognise a
  // report you asked for, and "batch_number=BATCH-1" is the API's phrasing, not theirs.
  return parts
    .map(([key, value]) => {
      const text = Array.isArray(value) ? value.join(", ") : String(value);
      return `${filterLabel(key, t)} ${text}`;
    })
    .join(" · ");
}

function reportLanguage(report: Report): ReportLanguage {
  const raw = (report.filters ?? {}).language;
  return raw === "pt" ? "pt" : "en";
}

/** Batch, then boards of that batch. Typing a batch number by
 * hand was the single largest source of empty reports: nothing told the operator whether the
 * batch existed, whether it had finished processing, or how its boards were named. Both lists
 * are read from what the system actually holds, so an unreachable scope cannot be requested.
 */
function ScopePicker({
  type,
  batchNumber,
  onBatchChange,
  boards,
  boardsLoading,
  selectedBoards,
  onSelectedBoardsChange,
  inspectionId,
  onInspectionIdChange,
}: {
  type: "individual" | "consolidated";
  batchNumber: string;
  onBatchChange: (next: string) => void;
  boards: InspectionListItem[];
  boardsLoading: boolean;
  selectedBoards: string[];
  onSelectedBoardsChange: (next: string[]) => void;
  inspectionId: string;
  onInspectionIdChange: (next: string) => void;
}) {
  const { t } = useI18n();
  const batchesQuery = useQuery({
    queryKey: ["reports", "batch-options"],
    queryFn: () => listBatches({ page: 1, page_size: BATCH_OPTIONS_PAGE_SIZE }),
  });

  const batches = batchesQuery.data?.results ?? [];
  const namedBoards = boards.filter((board) => board.board_number);

  function toggleBoard(boardNumber: string) {
    onSelectedBoardsChange(
      selectedBoards.includes(boardNumber)
        ? selectedBoards.filter((item) => item !== boardNumber)
        : [...selectedBoards, boardNumber]
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="field max-w-md">
        <Label htmlFor="report-batch">{t("reports.scope.batch")}</Label>
        <select
          id="report-batch"
          className={SELECT_CLASS}
          value={batchNumber}
          onChange={(event) => onBatchChange(event.target.value)}
        >
          <option value="">
            {type === "individual" ? t("reports.scope.selectBatch") : t("reports.scope.allBatches")}
          </option>
          {batches.map((batch) => (
            <option key={batch.batch_id} value={batch.batch_number}>
              {t("reports.scope.batchOption", {
                batch: batch.batch_number,
                completed: batch.completed_count,
                total: batch.board_count,
                defects: batch.defect_count,
              })}
            </option>
          ))}
        </select>
        {batchesQuery.isSuccess && batches.length === 0 && (
          <p className="text-xs text-muted-foreground">{t("reports.scope.noBatches")}</p>
        )}
        {batchesQuery.isError && (
          <p className="text-xs text-destructive">{t("reports.scope.batchesFailed")}</p>
        )}
      </div>

      {type === "individual" ? (
        <div className="field max-w-md">
          <Label htmlFor="report-board">{t("reports.scope.board")}</Label>
          <select
            id="report-board"
            className={SELECT_CLASS}
            value={inspectionId}
            disabled={!batchNumber || boardsLoading}
            onChange={(event) => onInspectionIdChange(event.target.value)}
          >
            <option value="">
              {!batchNumber
                ? t("reports.scope.selectBatchFirst")
                : boardsLoading
                  ? t("reports.scope.loadingBoards")
                  : t("reports.scope.selectBoard")}
            </option>
            {boards.map((board) => (
              <option key={board.id} value={board.id}>
                {boardLabel(board, t)}
                {board.severity_max ? ` (${t(`severity.${board.severity_max}`)})` : ""}
              </option>
            ))}
          </select>
          {batchNumber && !boardsLoading && boards.length === 0 && (
            <p className="text-xs text-muted-foreground">{t("reports.scope.noBoards")}</p>
          )}
        </div>
      ) : (
        batchNumber && (
          <div className="field">
            <span id="report-boards-label" className="field-label">
              {t("reports.scope.boards")}
            </span>
            <p className="text-xs text-muted-foreground">{t("reports.scope.boardsHint")}</p>
            {boardsLoading ? (
              <p className="text-sm text-muted-foreground">{t("reports.scope.loadingBoards")}</p>
            ) : namedBoards.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("reports.scope.noNamedBoards")}</p>
            ) : (
              <div
                role="group"
                aria-labelledby="report-boards-label"
                className="flex max-h-48 flex-wrap gap-x-4 gap-y-2 overflow-y-auto rounded-lg border border-border p-3"
              >
                {namedBoards.map((board) => (
                  <label key={board.id} className="flex items-center gap-1.5 text-sm">
                    <input
                      type="checkbox"
                      className="control-check"
                      checked={selectedBoards.includes(board.board_number as string)}
                      onChange={() => toggleBoard(board.board_number as string)}
                    />
                    {boardLabel(board, t)}
                  </label>
                ))}
              </div>
            )}
            {selectedBoards.length > 0 && (
              <Button
                variant="outline"
                size="sm"
                className="w-fit"
                onClick={() => onSelectedBoardsChange([])}
              >
                {t("reports.scope.clearBoards")}
              </Button>
            )}
          </div>
        )
      )}
    </div>
  );
}

function RequestReportForm({ onRequested }: { onRequested: () => void }) {
  const { language: stationLanguage, t } = useI18n();
  const [type, setType] = useState<ReportType>("consolidated");
  const [format, setFormat] = useState<ReportFormat>("pdf");
  // The report comes out in the language the station is set to, which is the one the operator
  // is reading the screen in. It stays overridable per report (a batch report for a customer
  // abroad), and switching the station language resets the field rather than leaving a stale
  // choice behind.
  const [language, setLanguage] = useState<ReportLanguage>(stationLanguage);
  const [batchNumber, setBatchNumber] = useState("");
  const [inspectionId, setInspectionId] = useState("");
  const [selectedBoards, setSelectedBoards] = useState<string[]>([]);
  const [filters, setFilters] = useState<InspectionFilterValues>(EMPTY_INSPECTION_FILTERS);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setLanguage(stationLanguage);
  }, [stationLanguage]);

  const boardsQuery = useQuery({
    queryKey: ["reports", "board-options", batchNumber],
    queryFn: () =>
      listInspections({
        batch_number: batchNumber,
        page: 1,
        page_size: BOARD_OPTIONS_PAGE_SIZE,
        ordering: "created_at",
      }),
    enabled: type !== "executive" && batchNumber !== "",
  });

  const boards = useMemo(
    () => (batchNumber ? (boardsQuery.data?.results ?? []) : []),
    [batchNumber, boardsQuery.data]
  );

  function changeType(next: ReportType) {
    setType(next);
    setFormat(FORMATS_BY_TYPE[next][0]);
    setError(null);
  }

  function changeBatch(next: string) {
    setBatchNumber(next);
    // The board pickers are scoped to the batch, so their previous values no longer name
    // anything that exists.
    setInspectionId("");
    setSelectedBoards([]);
    setError(null);
  }

  async function submit() {
    setError(null);

    if (type === "individual" && !inspectionId) {
      setError(t("reports.form.missingBoard"));
      return;
    }

    setSubmitting(true);
    try {
      if (type === "individual") {
        await requestReport({
          type: "individual",
          format,
          inspection_id: inspectionId,
          language,
        });
      } else if (type === "consolidated") {
        await requestReport({
          type: "consolidated",
          format,
          language,
          filters: {
            defect_type: filters.defect_type.length > 0 ? filters.defect_type : undefined,
            batch_number: batchNumber || undefined,
            board_numbers: selectedBoards.length > 0 ? selectedBoards : undefined,
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
          language,
          date_from: dateFrom ? `${dateFrom}T00:00:00Z` : undefined,
          date_to: dateTo ? `${dateTo}T23:59:59Z` : undefined,
        });
      }
      setInspectionId("");
      setSelectedBoards([]);
      setFilters(EMPTY_INSPECTION_FILTERS);
      setDateFrom("");
      setDateTo("");
      onRequested();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("reports.form.failed"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("reports.form.title")}</CardTitle>
        <CardDescription>{t("reports.form.description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid max-w-3xl grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="field">
            <Label htmlFor="report-type">{t("reports.form.type")}</Label>
            <select
              id="report-type"
              className={SELECT_CLASS}
              value={type}
              onChange={(event) => changeType(event.target.value as ReportType)}
            >
              {REPORT_TYPES.map((value) => (
                <option key={value} value={value}>
                  {t(`reports.type.${value}`)}
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">{t(`reports.typeHint.${type}`)}</p>
          </div>
          <div className="field">
            <Label htmlFor="report-format">{t("reports.form.format")}</Label>
            <select
              id="report-format"
              className={SELECT_CLASS}
              value={format}
              disabled={FORMATS_BY_TYPE[type].length === 1}
              onChange={(event) => setFormat(event.target.value as ReportFormat)}
            >
              {FORMATS_BY_TYPE[type].map((value) => (
                <option key={value} value={value}>
                  {value.toUpperCase()}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <Label htmlFor="report-language">{t("reports.form.language")}</Label>
            <select
              id="report-language"
              className={SELECT_CLASS}
              value={language}
              onChange={(event) => setLanguage(event.target.value as ReportLanguage)}
            >
              {LANGUAGES.map((value) => (
                <option key={value} value={value}>
                  {t(`reports.language.${value}`)}
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">{t("reports.form.languageHint")}</p>
          </div>
        </div>

        {type !== "executive" && (
          <ScopePicker
            type={type}
            batchNumber={batchNumber}
            onBatchChange={changeBatch}
            boards={boards}
            boardsLoading={boardsQuery.isPending && batchNumber !== ""}
            selectedBoards={selectedBoards}
            onSelectedBoardsChange={setSelectedBoards}
            inspectionId={inspectionId}
            onInspectionIdChange={setInspectionId}
          />
        )}

        {type === "consolidated" && (
          <FilterBar mode="reports" value={filters} onChange={setFilters} />
        )}

        {type === "executive" && (
          <div className="grid max-w-md grid-cols-2 gap-4">
            <div className="field">
              <Label htmlFor="report-date-from">{t("reports.form.from")}</Label>
              <Input
                id="report-date-from"
                type="date"
                value={dateFrom}
                onChange={(event) => setDateFrom(event.target.value)}
              />
            </div>
            <div className="field">
              <Label htmlFor="report-date-to">{t("reports.form.to")}</Label>
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
          {/* The page's one primary action, so it carries the brand face; everything else on
              this screen is an outline control. */}
          <Button
            size="sm"
            variant="brand"
            className="w-fit"
            disabled={submitting}
            onClick={() => void submit()}
          >
            {submitting ? t("reports.form.submitting") : t("reports.form.submit")}
          </Button>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

/** Download with visible state: a PDF over a slow disk can
 * take a couple of seconds, and the old button did nothing visible in the meantime, so
 * operators clicked it repeatedly and could not tell whether the file had been saved.
 */
function ReportActionCell({ report }: { report: Report }) {
  const { t } = useI18n();
  const [state, setState] = useState<"idle" | "downloading" | "done">("idle");
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  if (report.status === "PENDING") {
    return <span className="text-xs text-muted-foreground">{t("reports.action.waiting")}</span>;
  }

  if (report.status === "FAILED") {
    return (
      <span className="max-w-64 text-xs text-destructive">
        {report.error_message ?? t("reports.action.generationFailed")}
      </span>
    );
  }

  async function handleDownload() {
    if (timerRef.current) clearTimeout(timerRef.current);
    setState("downloading");
    setError(null);
    try {
      await downloadReport(report);
      setState("done");
      timerRef.current = setTimeout(() => setState("idle"), DOWNLOAD_CONFIRMATION_MS);
    } catch (err) {
      setState("idle");
      setError(err instanceof ApiError ? err.message : t("reports.action.downloadFailed"));
    }
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <Button
        size="sm"
        variant="outline"
        disabled={state === "downloading"}
        aria-busy={state === "downloading"}
        onClick={() => void handleDownload()}
      >
        {state === "downloading"
          ? t("reports.action.preparing")
          : state === "done"
            ? t("reports.action.downloadAgain")
            : t("common.download")}
      </Button>
      <span aria-live="polite" className="text-xs text-muted-foreground">
        {state === "downloading"
          ? t("reports.action.preparingFile")
          : state === "done"
            ? t("reports.action.saved")
            : ""}
      </span>
      {error && <span className="text-xs text-destructive">{error}</span>}
    </div>
  );
}

export default function ReportsPage() {
  const { t } = useI18n();
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
      <PageHeader
        eyebrow={t("reports.eyebrow")}
        title={t("reports.title")}
        description={t("reports.description")}
      />

      <RequestReportForm onRequested={handleRequested} />

      <Card>
        <CardHeader>
          <CardTitle>
            {t("reports.list.title")}
            {listQuery.isSuccess ? ` (${total})` : ""}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("reports.column.type")}</TableHead>
                <TableHead>{t("reports.column.format")}</TableHead>
                <TableHead>{t("reports.column.language")}</TableHead>
                <TableHead>{t("reports.column.details")}</TableHead>
                <TableHead>{t("reports.column.status")}</TableHead>
                <TableHead>{t("reports.column.requested")}</TableHead>
                <TableHead>{t("reports.column.action")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(listQuery.data?.results ?? []).map((report) => (
                <TableRow key={report.id}>
                  <TableCell className="font-medium">{t(`reports.type.${report.type}`)}</TableCell>
                  <TableCell className="uppercase">{report.format}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {t(`reports.language.${reportLanguage(report)}`)}
                  </TableCell>
                  <TableCell className="max-w-64 text-xs text-muted-foreground">
                    {describeFilters(report, t)}
                  </TableCell>
                  <TableCell>
                    <ReportStatusChip status={report.status} />
                  </TableCell>
                  <TableCell className="readout text-xs whitespace-nowrap text-muted-foreground">
                    {formatTimestamp(report.created_at)}
                  </TableCell>
                  <TableCell>
                    <ReportActionCell report={report} />
                  </TableCell>
                </TableRow>
              ))}
              {listQuery.isSuccess && total === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="text-center text-sm text-muted-foreground">
                    {t("reports.empty")}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>

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
                  onClick={() => setPage((current) => current - 1)}
                >
                  {t("common.previous")}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((current) => current + 1)}
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
