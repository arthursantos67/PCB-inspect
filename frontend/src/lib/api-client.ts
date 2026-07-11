import { type CurrentUser, getSession, setSession } from "@/lib/auth-store";

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

async function throwApiError(response: Response): Promise<never> {
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

// --- Settings config (FR-13, scoped to ingestion keys for now) -------------------------

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
