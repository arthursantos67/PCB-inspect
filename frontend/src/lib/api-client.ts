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

export type InspectionListItem = {
  id: string;
  status: ImageStatus;
  batch_number: string | null;
  board_number: string | null;
  defect_types: DefectType[];
  severity_max: Severity | null;
  review_status: "PENDING" | "VALIDATED" | "REJECTED" | null;
  disposition_recommendation: "approve" | "rework" | "discard" | null;
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
  if (params.date_from) search.set("date_from", params.date_from);
  if (params.date_to) search.set("date_to", params.date_to);
  return apiFetch(`/api/v1/inspections?${search.toString()}`);
}

// --- Inspection detail (FE-03, section 11.5) --------------------------------------------

export type BBox = { x1: number; y1: number; x2: number; y2: number };

export type Detection = {
  id: string;
  defect_type: DefectType;
  bbox: BBox;
  // Serialized as a string by Pydantic's Decimal encoding, not a JSON number.
  confidence: string;
  is_reported: boolean;
  model_version: string;
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
};

export async function getInspection(id: string): Promise<InspectionDetail> {
  return apiFetch(`/api/v1/inspections/${id}`);
}

export type ImageVariant = "original" | "annotated";

export function inspectionImagePath(id: string, variant: ImageVariant): string {
  return `/api/v1/inspections/${id}/image?variant=${variant}`;
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
