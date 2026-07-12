// Session state is persisted to localStorage (PRD FE-01/section 13) so it survives a reload,
// a connection-error page, or the launcher window restarting — the app never leaves
// localhost, so a network attacker can't intercept the token in transit either way; the only
// thing that should end a session is an explicit logout. A plain module-level singleton
// (rather than React state), backed by localStorage, lets the non-React api-client
// read/replace the current token on every request, while AuthContext mirrors it into React
// via useSyncExternalStore.

export type CurrentUser = {
  id: string;
  email: string;
  full_name: string;
  created_at: string;
};

export type Session = {
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
  user: CurrentUser;
};

const STORAGE_KEY = "pcb-inspect-session";

function loadPersistedSession(): Session | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

let currentSession: Session | null = loadPersistedSession();
const listeners = new Set<() => void>();

export function getSession(): Session | null {
  return currentSession;
}

export function setSession(next: Session | null): void {
  currentSession = next;
  if (typeof window !== "undefined") {
    try {
      if (next) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // localStorage unavailable (private browsing, quota exceeded) — session still works
      // for the rest of this tab's lifetime, it just won't survive a reload.
    }
  }
  for (const listener of listeners) listener();
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
