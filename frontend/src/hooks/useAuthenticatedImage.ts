"use client";

import { useEffect, useState } from "react";

import { getSession } from "@/lib/auth-store";
import { inspectionImagePath, type ImageVariant } from "@/lib/api-client";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type AuthenticatedImageState = {
  url: string | null;
  isLoading: boolean;
  isError: boolean;
};

/** Fetches `GET /api/v1/inspections/{id}/image` (FE-03, section 3.1) as a blob and exposes
 * it as an object URL. A plain `<img src>` can't carry the bearer token — the session is
 * kept in memory only, never a cookie or the URL (FE-01/section 13) — so this reads the
 * response manually via `fetch()`, mirroring `useEventStream`.
 */
export function useAuthenticatedImage(
  inspectionId: string,
  variant: ImageVariant,
  { enabled = true }: { enabled?: boolean } = {}
): AuthenticatedImageState {
  const [state, setState] = useState<AuthenticatedImageState>({
    url: null,
    isLoading: enabled,
    isError: false,
  });

  useEffect(() => {
    if (!enabled) {
      setState({ url: null, isLoading: false, isError: false });
      return;
    }

    let cancelled = false;
    let objectUrl: string | null = null;
    setState({ url: null, isLoading: true, isError: false });

    async function load() {
      try {
        const session = getSession();
        const response = await fetch(`${API_URL}${inspectionImagePath(inspectionId, variant)}`, {
          headers: session ? { Authorization: `Bearer ${session.accessToken}` } : {},
        });
        if (!response.ok) throw new Error(`Image fetch failed with status ${response.status}`);
        const blob = await response.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setState({ url: objectUrl, isLoading: false, isError: false });
      } catch {
        if (!cancelled) setState({ url: null, isLoading: false, isError: true });
      }
    }

    void load();

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [inspectionId, variant, enabled]);

  return state;
}
