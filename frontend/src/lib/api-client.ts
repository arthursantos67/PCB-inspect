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
  headers.set("Content-Type", "application/json");
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
