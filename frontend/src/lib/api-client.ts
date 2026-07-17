import { type CurrentUser, getSession, setSession } from "@/lib/auth-store";
import type { DefectType, Severity } from "@/lib/chart-colors";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  code: string;
  status: number;
  details: Record<string, unknown>;

  constructor(code: string, message: string, status: number, details: Record<string, unknown> = {}) {
    super(message);
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

type TokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: CurrentUser;
};

function applyTokenResponse(body: TokenResponse): CurrentUser {
  setSession({
    accessToken: body.access_token,
    refreshToken: body.refresh_token,
    expiresAt: Date.now() + body.expires_in * 1000,
    user: body.user,
  });
  return body.user;
}

export async function throwApiError(response: Response): Promise<never> {
  let code = "INTERNAL_SERVER_ERROR";
  let message = response.statusText || "Request failed";
  let details: Record<string, unknown> = {};
  try {
    const body = await response.json();
    if (body?.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      details = body.error.details ?? {};
    }
  } catch {
    // No JSON body to parse — fall back to the status text above.
  }
  throw new ApiError(code, message, response.status, details);
}

/** Refreshes the access token in place. Returns false (and clears the session) on failure. */
export async function refreshSession(): Promise<boolean> {
  const session = getSession();
  if (!session) return false;

  const response = await fetch(`${API_URL}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: session.refreshToken }),
  });

  if (!response.ok) {
    setSession(null);
    return false;
  }

  applyTokenResponse(await response.json());
  return true;
}

/** Authenticated fetch wrapper: attaches the bearer token and retries once after a 401 refresh. */
export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  { retryOn401 = true }: { retryOn401?: boolean } = {}
): Promise<T> {
  const session = getSession();
  const headers = new Headers(init.headers);
  // Leave FormData bodies alone — the browser sets the multipart boundary itself.
  if (!(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (session) headers.set("Authorization", `Bearer ${session.accessToken}`);

  const response = await fetch(`${API_URL}${path}`, { ...init, headers });

  if (response.status === 401 && retryOn401 && session) {
    if (await refreshSession()) {
      return apiFetch<T>(path, init, { retryOn401: false });
    }
  }

  if (!response.ok) {
    await throwApiError(response);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function getSetupStatus(): Promise<{ setup_required: boolean }> {
  return apiFetch("/api/v1/auth/setup");
}

export async function setupAccount(payload: {
  email: string;
  password: string;
  full_name: string;
}): Promise<CurrentUser> {
  const body = await apiFetch<TokenResponse>("/api/v1/auth/setup", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return applyTokenResponse(body);
}

export async function login(payload: { email: string; password: string }): Promise<CurrentUser> {
  const body = await apiFetch<TokenResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return applyTokenResponse(body);
}

export function logout(): void {
  setSession(null);
}

// --- Ingestion (FR-03, FE-05) -----------------------------------------------------------

export type FileOutcome = "ingested" | "duplicate" | "failed" | "skipped";

export type FileResult = {
  path: string;
  outcome: FileOutcome;
  image_id: string | null;
  reason: string | null;
};

export type ScanSummary = {
  path: string;
  discovered: number;
  ingested: number;
  duplicate: number;
  failed: number;
  skipped: number;
  files: FileResult[];
};

export type ImportSummary = {
  ingested: number;
  duplicate: number;
  failed: number;
  files: FileResult[];
};

export type WatchStatus = "watching" | "paused" | "not_configured" | "error";

export type IngestionStatus = {
  status: WatchStatus;
  watch_root_path: string | null;
  watch_mode_enabled: boolean;
  files_discovered: number;
  files_ingested: number;
  files_failed: number;
  detail: string | null;
};

export async function getIngestionStatus(): Promise<IngestionStatus> {
  return apiFetch("/api/v1/inspections/ingestion-status");
}

export async function scanDirectory(path: string): Promise<ScanSummary> {
  return apiFetch("/api/v1/inspections/scan", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

export async function importFiles(files: File[]): Promise<ImportSummary> {
  const formData = new FormData();
  for (const file of files) formData.append("files", file);
  return apiFetch("/api/v1/inspections/import", { method: "POST", body: formData });
}

// --- Settings config (FR-13) -------------------------------------------------------------

export type ConfigResponse = { config: Record<string, unknown> };

export async function getConfig(): Promise<ConfigResponse> {
  return apiFetch("/api/v1/settings/config");
}

export async function updateConfig(config: Record<string, unknown>): Promise<ConfigResponse> {
  return apiFetch("/api/v1/settings/config", {
    method: "PATCH",
    body: JSON.stringify({ config }),
  });
}

export type LlmProvider = "openai_compatible" | "anthropic" | "google";
export type AgentAnalysisMode = "conditional" | "always" | "on_demand";

export type SecretConfigValue = { configured: boolean; last4: string | null };

// --- Model versions (FR-12, NFR-05) -------------------------------------------------------

export type ModelEvaluationStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";

export type ModelMetrics = {
  map50: number;
  map50_95: number;
  per_class: Record<string, number>;
  golden_set_version?: string;
  image_count?: number;
};

export type ModelVersion = {
  id: string;
  version: string;
  weights_path: string;
  metrics: ModelMetrics | null;
  evaluation_status: ModelEvaluationStatus;
  evaluation_error: string | null;
  is_active: boolean;
  activated_at: string | null;
  created_at: string;
};

export async function listModelVersions(): Promise<ModelVersion[]> {
  return apiFetch("/api/v1/settings/models");
}

export async function registerModelVersion(payload: {
  version: string;
  weights_path: string;
}): Promise<ModelVersion> {
  return apiFetch("/api/v1/settings/models", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getModelEvaluation(id: string): Promise<ModelVersion> {
  return apiFetch(`/api/v1/settings/models/${id}/evaluation`);
}

export async function activateModelVersion(
  id: string,
  payload: { override?: boolean; justification?: string } = {}
): Promise<ModelVersion> {
  return apiFetch(`/api/v1/settings/models/${id}/activate`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// --- Health (FR-15) ----------------------------------------------------------------------

export type HealthStatus = "ok" | "error" | "not_configured";

export type HealthCheckResult = { status: HealthStatus; detail: string | null };

export type HealthReport = {
  status: "ok" | "degraded";
  db: HealthCheckResult;
  redis: HealthCheckResult;
  worker: HealthCheckResult & {
    model_loaded: boolean;
    device: string | null;
    model_version: string | null;
  };
  watch_root: HealthCheckResult;
  llm: HealthCheckResult;
};

export async function getHealth(): Promise<HealthReport> {
  return apiFetch("/health");
}

// --- Stats (FR-08, FE-02) ---------------------------------------------------------------

export type StatsSummary = {
  total_inspected: number;
  total_with_defects: number;
  quality_rate: number;
  last_24h_count: number;
  analyses_validated: number;
  analyses_rejected: number;
  analysis_precision_rate: number | null;
};

export type TrendPeriod = "7d" | "30d" | "90d";
export type TrendGranularity = "day" | "week" | "month";

export type TrendPoint = {
  bucket: string;
  total: number;
  by_defect_type: Partial<Record<DefectType, number>>;
};

export type StatsTrends = {
  period: TrendPeriod;
  granularity: TrendGranularity;
  points: TrendPoint[];
};

export type StatsByDefectType = {
  total: number;
  counts: { defect_type: DefectType; count: number }[];
};

export async function getStatsSummary(): Promise<StatsSummary> {
  return apiFetch("/api/v1/stats/summary");
}

export async function getStatsTrends(
  period: TrendPeriod,
  granularity: TrendGranularity = "day"
): Promise<StatsTrends> {
  return apiFetch(`/api/v1/stats/trends?period=${period}&granularity=${granularity}`);
}

export async function getStatsByDefectType(): Promise<StatsByDefectType> {
  return apiFetch("/api/v1/stats/by-defect-type");
}

// --- Inspections listing (FR-07) — used by the dashboard's recent-analyses table (FE-02) ---

export type ImageStatus =
  | "QUEUED"
  | "PROCESSING"
  | "DETECTED"
  | "ANALYZING"
  | "COMPLETED"
  | "FAILED";

export type BoardDispositionDecision = "approved" | "rework" | "discarded";

export type InspectionListItem = {
  id: string;
  status: ImageStatus;
  batch_number: string | null;
  board_number: string | null;
  defect_types: DefectType[];
  severity_max: Severity | null;
  review_status: "PENDING" | "VALIDATED" | "REJECTED" | null;
  disposition_recommendation: "approve" | "rework" | "discard" | null;
  disposition: BoardDispositionDecision | null;
  failure_reason: string | null;
  created_at: string;
  processed_at: string | null;
};

export type PaginatedInspections = {
  count: number;
  next: string | null;
  previous: string | null;
  results: InspectionListItem[];
};

export async function listInspections(params: {
  page?: number;
  page_size?: number;
  ordering?: string;
  defect_type?: DefectType[];
  batch_number?: string;
  board_number?: string;
  status?: ImageStatus;
  severity?: Severity;
  review_status?: "PENDING" | "VALIDATED" | "REJECTED";
  disposition?: BoardDispositionDecision;
  date_from?: string;
  date_to?: string;
}): Promise<PaginatedInspections> {
  const search = new URLSearchParams();
  if (params.page) search.set("page", String(params.page));
  if (params.page_size) search.set("page_size", String(params.page_size));
  if (params.ordering) search.set("ordering", params.ordering);
  for (const defectType of params.defect_type ?? []) search.append("defect_type", defectType);
  if (params.batch_number) search.set("batch_number", params.batch_number);
  if (params.board_number) search.set("board_number", params.board_number);
  if (params.status) search.set("status", params.status);
  if (params.severity) search.set("severity", params.severity);
  if (params.review_status) search.set("review_status", params.review_status);
  if (params.disposition) search.set("disposition", params.disposition);
  if (params.date_from) search.set("date_from", params.date_from);
  if (params.date_to) search.set("date_to", params.date_to);
  return apiFetch(`/api/v1/inspections?${search.toString()}`);
}

// --- Inspection detail (FE-03, section 11.5) --------------------------------------------

export type BBox = { x1: number; y1: number; x2: number; y2: number };

export type DetectionReview = "unreviewed" | "confirmed" | "false_positive";
export type DetectionSource = "model" | "manual";

export type Detection = {
  id: string;
  defect_type: DefectType;
  bbox: BBox;
  // Serialized as a string by Pydantic's Decimal encoding, not a JSON number.
  confidence: string;
  is_reported: boolean;
  // null for a manually-drawn detection (FR-10) — it has no producing model version.
  model_version: string | null;
  review: DetectionReview;
  source: DetectionSource;
};

export type InspectionBoardInfo = {
  board_number: string | null;
  batch_number: string | null;
};

export type PerDefectEntry = {
  detection_id: string;
  description: string;
  probable_causes: string[];
  suggested_solutions: string[];
  severity: Severity;
};

export type AnalysisStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "NEEDS_HUMAN_REVIEW";
export type AnalysisSource = "knowledge_base" | "agents";
export type AnalysisReviewAction = "validated" | "rejected";

export type AnalysisReview = {
  id: string;
  reviewer_id: string;
  action: AnalysisReviewAction;
  comment: string | null;
  created_at: string;
};

export type Analysis = {
  id: string;
  image_id: string;
  status: AnalysisStatus;
  source: AnalysisSource;
  severity_max: Severity | null;
  disposition_recommendation: "approve" | "rework" | "discard" | null;
  executive_summary: string | null;
  per_defect: PerDefectEntry[] | null;
  review_status: "PENDING" | "VALIDATED" | "REJECTED";
  reviews: AnalysisReview[];
  created_at: string;
};

export type BoardDisposition = {
  id: string;
  image_id: string;
  decision: BoardDispositionDecision;
  decided_by: string;
  created_at: string;
};

export type InspectionDetail = {
  id: string;
  status: ImageStatus;
  board: InspectionBoardInfo;
  failure_reason: string | null;
  created_at: string;
  processed_at: string | null;
  duration_ms: number | null;
  detections: Detection[];
  analysis: Analysis | null;
  disposition: BoardDisposition | null;
};

export async function getInspection(id: string): Promise<InspectionDetail> {
  return apiFetch(`/api/v1/inspections/${id}`);
}

export type ImageVariant = "original" | "annotated";

export function inspectionImagePath(id: string, variant: ImageVariant): string {
  return `/api/v1/inspections/${id}/image?variant=${variant}`;
}

// --- Review, feedback, disposition & manual annotation (FR-10) --------------------------

export async function reviewAnalysis(
  analysisId: string,
  action: AnalysisReviewAction,
  comment?: string
): Promise<Analysis> {
  return apiFetch(`/api/v1/analyses/${analysisId}/review`, {
    method: "POST",
    body: JSON.stringify({ action, comment: comment || null }),
  });
}

export async function submitDetectionFeedback(
  detectionId: string,
  review: "confirmed" | "false_positive"
): Promise<Detection> {
  return apiFetch(`/api/v1/detections/${detectionId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ review }),
  });
}

export async function setBoardDisposition(
  inspectionId: string,
  decision: BoardDispositionDecision
): Promise<BoardDisposition> {
  return apiFetch(`/api/v1/inspections/${inspectionId}/disposition`, {
    method: "POST",
    body: JSON.stringify({ decision }),
  });
}

export async function annotateInspection(
  inspectionId: string,
  defectType: DefectType,
  bbox: BBox
): Promise<Detection> {
  return apiFetch(`/api/v1/inspections/${inspectionId}/annotations`, {
    method: "POST",
    body: JSON.stringify({ defect_type: defectType, bbox }),
  });
}

// --- Reports (FR-11, FE-07) --------------------------------------------------------------

export type ReportType = "individual" | "consolidated" | "executive";
export type ReportFormat = "csv" | "xlsx" | "pdf";
export type ReportStatus = "PENDING" | "COMPLETED" | "FAILED";

export type Report = {
  id: string;
  type: ReportType;
  format: ReportFormat;
  filters: Record<string, unknown> | null;
  status: ReportStatus;
  file_path: string | null;
  row_count: number | null;
  error_message: string | null;
  requested_by: string;
  created_at: string;
};

export type PaginatedReports = {
  count: number;
  next: string | null;
  previous: string | null;
  results: Report[];
};

export type ReportFiltersInput = {
  defect_type?: DefectType[];
  batch_number?: string;
  board_number?: string;
  status?: ImageStatus;
  severity?: Severity;
  review_status?: "PENDING" | "VALIDATED" | "REJECTED";
  disposition?: BoardDispositionDecision;
  date_from?: string;
  date_to?: string;
};

export type ReportRequestPayload =
  | { type: "individual"; format: "pdf"; inspection_id: string }
  | { type: "consolidated"; format: ReportFormat; filters?: ReportFiltersInput }
  | { type: "executive"; format: "pdf"; date_from?: string; date_to?: string };

export async function requestReport(payload: ReportRequestPayload): Promise<Report> {
  return apiFetch("/api/v1/reports", { method: "POST", body: JSON.stringify(payload) });
}

export async function listReports(params: { page?: number; page_size?: number } = {}): Promise<
  PaginatedReports
> {
  const search = new URLSearchParams();
  if (params.page) search.set("page", String(params.page));
  if (params.page_size) search.set("page_size", String(params.page_size));
  const query = search.toString();
  return apiFetch(`/api/v1/reports${query ? `?${query}` : ""}`);
}

export function reportDownloadPath(id: string): string {
  return `/api/v1/reports/${id}/download`;
}

/** Downloads the report's file through the authenticated fetch wrapper and saves it via a
 * throwaway `<a>` + object URL — matches this app never putting the session token in a URL
 * (section 13/FE-01), so the file can't be fetched with a plain `<a href>` alone.
 */
export async function downloadReport(report: Report): Promise<void> {
  const session = getSession();
  const headers: Record<string, string> = {};
  if (session) headers.Authorization = `Bearer ${session.accessToken}`;

  const response = await fetch(`${API_URL}${reportDownloadPath(report.id)}`, { headers });
  if (!response.ok) {
    await throwApiError(response);
    return;
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${report.type}-${report.id}.${report.format}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// --- Dataset exports (FR-18) --------------------------------------------------------------

export type DatasetExportStatus = "PENDING" | "COMPLETED" | "FAILED";

export type DatasetExportManifest = {
  export_id: string;
  filters: Record<string, unknown>;
  classes: string[];
  statistics: {
    image_count: number;
    label_count: number;
    by_defect_type: Record<string, number>;
    by_review_status: Record<string, number>;
  };
  model_versions: { id: string; version: string }[];
};

export type DatasetExport = {
  id: string;
  filters: Record<string, unknown> | null;
  status: DatasetExportStatus;
  manifest: DatasetExportManifest | null;
  file_path: string | null;
  error_message: string | null;
  requested_by: string;
  created_at: string;
};

export type PaginatedDatasetExports = {
  count: number;
  next: string | null;
  previous: string | null;
  results: DatasetExport[];
};

export type DatasetExportFiltersInput = {
  defect_type?: DefectType[];
  review_status?: ("confirmed" | "false_positive")[];
  date_from?: string;
  date_to?: string;
};

export async function requestDatasetExport(
  filters: DatasetExportFiltersInput = {}
): Promise<DatasetExport> {
  return apiFetch("/api/v1/dataset-exports", {
    method: "POST",
    body: JSON.stringify({ filters }),
  });
}

export async function listDatasetExports(
  params: { page?: number; page_size?: number } = {}
): Promise<PaginatedDatasetExports> {
  const search = new URLSearchParams();
  if (params.page) search.set("page", String(params.page));
  if (params.page_size) search.set("page_size", String(params.page_size));
  const query = search.toString();
  return apiFetch(`/api/v1/dataset-exports${query ? `?${query}` : ""}`);
}

export function datasetExportDownloadPath(id: string): string {
  return `/api/v1/dataset-exports/${id}/download`;
}

/** Same authenticated-blob-download pattern as `downloadReport` — the session token never
 * goes in a URL (section 13/FE-01), so a plain `<a href>` can't fetch this directly.
 */
export async function downloadDatasetExport(datasetExport: DatasetExport): Promise<void> {
  const session = getSession();
  const headers: Record<string, string> = {};
  if (session) headers.Authorization = `Bearer ${session.accessToken}`;

  const response = await fetch(`${API_URL}${datasetExportDownloadPath(datasetExport.id)}`, {
    headers,
  });
  if (!response.ok) {
    await throwApiError(response);
    return;
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `dataset-export-${datasetExport.id}.zip`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// --- Quality alerts (FR-19, FE-02) --------------------------------------------------------

export type QualityAlertType = "defect_rate_batch" | "defect_rate_window";
export type QualityAlertStatus = "active" | "acknowledged";

export type QualityAlertContext = {
  observed_rate: number;
  threshold: number;
  batch_id?: string;
  batch_number?: string;
  window_minutes?: number;
  sample_size?: number;
};

export type QualityAlert = {
  id: string;
  type: QualityAlertType;
  context: QualityAlertContext;
  status: QualityAlertStatus;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  created_at: string;
};

export type PaginatedAlerts = {
  count: number;
  next: string | null;
  previous: string | null;
  results: QualityAlert[];
};

export async function listAlerts(
  params: { acknowledged?: boolean; page?: number; page_size?: number } = {}
): Promise<PaginatedAlerts> {
  const search = new URLSearchParams();
  if (params.acknowledged !== undefined) search.set("acknowledged", String(params.acknowledged));
  if (params.page) search.set("page", String(params.page));
  if (params.page_size) search.set("page_size", String(params.page_size));
  const query = search.toString();
  return apiFetch(`/api/v1/alerts${query ? `?${query}` : ""}`);
}

export async function acknowledgeAlert(id: string): Promise<QualityAlert> {
  return apiFetch(`/api/v1/alerts/${id}/ack`, { method: "POST" });
}

// --- Chat (FR-09, FE-06) -----------------------------------------------------------------

export type ChatRole = "user" | "assistant";

export type ChatToolCall = {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  result: unknown;
};

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  tool_calls: ChatToolCall[] | null;
  created_at: string;
};

export type ChatSession = {
  id: string;
  title: string | null;
  context_analysis_id: string | null;
  created_at: string;
  updated_at: string;
};

export type ChatSessionDetail = ChatSession & { messages: ChatMessage[] };

export async function createChatSession(contextAnalysisId?: string): Promise<ChatSession> {
  return apiFetch("/api/v1/chat/sessions", {
    method: "POST",
    body: JSON.stringify({ context_analysis_id: contextAnalysisId ?? null }),
  });
}

export async function listChatSessions(): Promise<{ results: ChatSession[] }> {
  return apiFetch("/api/v1/chat/sessions");
}

export async function getChatSession(id: string): Promise<ChatSessionDetail> {
  return apiFetch(`/api/v1/chat/sessions/${id}`);
}

export async function deleteChatSession(id: string): Promise<void> {
  await apiFetch(`/api/v1/chat/sessions/${id}`, { method: "DELETE" });
}

export type ChatStreamEvent =
  | { type: "tool_call"; name: string; arguments: Record<string, unknown> }
  | { type: "content_delta"; text: string }
  | { type: "error"; message: string }
  | { type: "done"; message: ChatMessage };

function parseChatSseChunk(raw: string): ChatStreamEvent | null {
  let eventType: string | null = null;
  let dataRaw: string | null = null;
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) eventType = line.slice("event:".length).trim();
    else if (line.startsWith("data:")) dataRaw = line.slice("data:".length).trim();
  }
  if (!eventType || dataRaw === null) return null;
  const data = JSON.parse(dataRaw);
  switch (eventType) {
    case "tool_call":
      return { type: "tool_call", name: data.name, arguments: data.arguments };
    case "content_delta":
      return { type: "content_delta", text: data.text };
    case "error":
      return { type: "error", message: data.message };
    case "done":
      return { type: "done", message: data as ChatMessage };
    default:
      return null;
  }
}

/**
 * Sends one chat turn and streams the response (FR-09, section 5.4) — incremental
 * `content_delta`/`tool_call` events as they arrive, terminated by exactly one `done` (or an
 * `error` immediately followed by `done`, UC-7's "LLM unavailable" alternative flow).
 *
 * Manual `fetch()` + SSE line reader, same rationale as `useEventStream` (FE-09): this is a
 * POST body, not something native `EventSource` can send at all.
 */
export async function sendChatMessage(
  sessionId: string,
  content: string,
  onEvent: (event: ChatStreamEvent) => void
): Promise<void> {
  const session = getSession();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (session) headers.Authorization = `Bearer ${session.accessToken}`;

  const response = await fetch(`${API_URL}/api/v1/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers,
    body: JSON.stringify({ content }),
  });
  if (!response.ok || !response.body) {
    await throwApiError(response);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const event = parseChatSseChunk(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
      if (event) onEvent(event);
    }
  }
}

// --- Accounts (FR-02, FE-08) -------------------------------------------------------------

export type Account = {
  id: string;
  email: string;
  full_name: string;
  created_at: string;
};

export async function listAccounts(): Promise<Account[]> {
  return apiFetch("/api/v1/users");
}

export async function createAccount(payload: {
  email: string;
  password: string;
  full_name: string;
}): Promise<Account> {
  return apiFetch("/api/v1/users", { method: "POST", body: JSON.stringify(payload) });
}

export async function updateAccount(
  id: string,
  payload: { email?: string; full_name?: string; password?: string }
): Promise<Account> {
  return apiFetch(`/api/v1/users/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export async function deleteAccount(id: string): Promise<void> {
  return apiFetch(`/api/v1/users/${id}`, { method: "DELETE" });
}

// --- Audit trail (FR-16, FE-08) -----------------------------------------------------------

// Every `action` string a `record_audit(...)` call currently uses across the backend
// (`app/audit/service.py` callers) — kept here as the single list the audit viewer's filter
// dropdown and label lookup both draw from, so a newly-audited action only needs one addition.
export const AUDIT_ACTIONS = [
  "account.created",
  "account.updated",
  "account.removed",
  "user.login",
  "config.updated",
  "model.activated",
  "model.evaluated",
  "model.evaluation_failed",
  "analysis.validated",
  "analysis.rejected",
  "board.disposition_set",
  "detection.reviewed",
  "detection.annotated",
  "alert.acknowledged",
] as const;

export type AuditAction = (typeof AUDIT_ACTIONS)[number];

export const AUDIT_ACTION_LABEL: Record<AuditAction, string> = {
  "account.created": "Account added",
  "account.updated": "Account updated",
  "account.removed": "Account removed",
  "user.login": "Login",
  "config.updated": "Configuration changed",
  "model.activated": "Model activated",
  "model.evaluated": "Model evaluated",
  "model.evaluation_failed": "Model evaluation failed",
  "analysis.validated": "Analysis validated",
  "analysis.rejected": "Analysis rejected",
  "board.disposition_set": "Board disposition set",
  "detection.reviewed": "Detection reviewed",
  "detection.annotated": "Detection annotated",
  "alert.acknowledged": "Alert acknowledged",
};

export type AuditActor = {
  id: string;
  email: string;
  full_name: string;
};

export type AuditLogEntry = {
  id: number;
  actor: AuditActor | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  payload: Record<string, unknown> | null;
  created_at: string;
};

export type PaginatedAuditLog = {
  count: number;
  next: string | null;
  previous: string | null;
  results: AuditLogEntry[];
};

export async function listAuditLog(
  params: {
    account_id?: string;
    action?: string;
    date_from?: string;
    date_to?: string;
    page?: number;
    page_size?: number;
  } = {}
): Promise<PaginatedAuditLog> {
  const search = new URLSearchParams();
  if (params.account_id) search.set("account_id", params.account_id);
  if (params.action) search.set("action", params.action);
  if (params.date_from) search.set("date_from", params.date_from);
  if (params.date_to) search.set("date_to", params.date_to);
  if (params.page) search.set("page", String(params.page));
  if (params.page_size) search.set("page_size", String(params.page_size));
  const query = search.toString();
  return apiFetch(`/api/v1/settings/audit${query ? `?${query}` : ""}`);
}
