// Session state lives only in memory (PRD FE-01/section 13 — never localStorage). A plain
// module-level singleton (rather than React state) lets the non-React api-client read/replace
// the current token on every request, while AuthContext mirrors it into React via
// useSyncExternalStore.

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

let currentSession: Session | null = null;
const listeners = new Set<() => void>();

export function getSession(): Session | null {
  return currentSession;
}

export function setSession(next: Session | null): void {
  currentSession = next;
  for (const listener of listeners) listener();
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
