"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
} from "react";

import * as api from "@/lib/api-client";
import { type CurrentUser, getSession, subscribe } from "@/lib/auth-store";

const REFRESH_MARGIN_MS = 60_000;
const MIN_REFRESH_DELAY_MS = 5_000;

type AuthContextValue = {
  user: CurrentUser | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  setup: (email: string, password: string, fullName: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function getServerSnapshot() {
  return null;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const session = useSyncExternalStore(subscribe, getSession, getServerSnapshot);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearRefreshTimer = useCallback(() => {
    if (refreshTimer.current !== null) {
      clearTimeout(refreshTimer.current);
      refreshTimer.current = null;
    }
  }, []);

  // Silent refresh before expiry (FE section 12.3); logout if the refresh itself fails.
  useEffect(() => {
    clearRefreshTimer();
    if (!session) return;

    const delay = Math.max(session.expiresAt - Date.now() - REFRESH_MARGIN_MS, MIN_REFRESH_DELAY_MS);
    refreshTimer.current = setTimeout(() => {
      void api.refreshSession().then((ok) => {
        if (!ok) api.logout();
      });
    }, delay);

    return clearRefreshTimer;
  }, [session, clearRefreshTimer]);

  const login = useCallback(async (email: string, password: string) => {
    await api.login({ email, password });
  }, []);

  const setup = useCallback(async (email: string, password: string, fullName: string) => {
    await api.setupAccount({ email, password, full_name: fullName });
  }, []);

  const logout = useCallback(() => {
    clearRefreshTimer();
    api.logout();
  }, [clearRefreshTimer]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user: session?.user ?? null,
      isAuthenticated: session !== null,
      login,
      setup,
      logout,
    }),
    [session, login, setup, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
