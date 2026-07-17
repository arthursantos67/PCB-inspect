"use client";

import { useEffect, useState } from "react";
import { type QueryClient, useQueryClient } from "@tanstack/react-query";

import { getSession } from "@/lib/auth-store";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const INITIAL_BACKOFF_MS = 1_000;
const MAX_BACKOFF_MS = 30_000;

export type EventStreamStatus = "connecting" | "connected" | "reconnecting" | "disconnected";

// Every event is treated purely as "something changed, refetch" (FE-09) — payloads aren't
// merged into the cache directly, so any pipeline event just invalidates the same two query
// key prefixes the dashboard (Issue 9) and history screen (Issue 10) will read from.
const INVALIDATED_QUERY_KEYS: readonly string[][] = [["inspections"], ["stats"], ["reports"]];

/**
 * Subscribes to `GET /api/v1/events` (FR-14) and invalidates TanStack Query caches on every
 * event, with automatic reconnection and exponential backoff (FE-09).
 *
 * Native `EventSource` can't send an `Authorization` header, so this reads the SSE stream
 * manually via `fetch()` instead — consistent with the rest of the app never putting the
 * session token in a URL (section 13/FE-01).
 */
export function useEventStream(enabled: boolean): EventStreamStatus {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<EventStreamStatus>("disconnected");

  useEffect(() => {
    if (!enabled) {
      setStatus("disconnected");
      return;
    }

    let cancelled = false;
    let backoffMs = INITIAL_BACKOFF_MS;
    const controller = new AbortController();

    async function connectLoop(): Promise<void> {
      while (!cancelled) {
        setStatus("connecting");
        try {
          const session = getSession();
          const response = await fetch(`${API_URL}/api/v1/events`, {
            headers: session ? { Authorization: `Bearer ${session.accessToken}` } : {},
            signal: controller.signal,
          });
          if (!response.ok || !response.body) {
            throw new Error(`SSE connection failed with status ${response.status}`);
          }
          setStatus("connected");
          backoffMs = INITIAL_BACKOFF_MS;
          await readEventStream(response.body, queryClient, () => cancelled);
        } catch {
          // Network error, dropped connection, or abort on cleanup — all handled by the
          // backoff/retry below; an aborted fetch on cleanup exits via the `cancelled` check.
        }
        if (cancelled) return;
        setStatus("reconnecting");
        await sleep(backoffMs, controller.signal);
        backoffMs = Math.min(backoffMs * 2, MAX_BACKOFF_MS);
      }
    }

    void connectLoop();

    return () => {
      cancelled = true;
      controller.abort();
      setStatus("disconnected");
    };
  }, [enabled, queryClient]);

  return status;
}

async function readEventStream(
  body: ReadableStream<Uint8Array>,
  queryClient: QueryClient,
  isCancelled: () => boolean
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (!isCancelled()) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      handleRawEvent(buffer.slice(0, boundary), queryClient);
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
    }
  }
}

function handleRawEvent(rawEvent: string, queryClient: QueryClient): void {
  let eventType: string | null = null;
  for (const line of rawEvent.split("\n")) {
    if (line.startsWith("event:")) {
      eventType = line.slice("event:".length).trim();
    }
    // ":"-prefixed lines are keep-alive comments; `data:` payloads aren't needed here since
    // every event triggers the same refetch-on-invalidation regardless of its contents.
  }
  if (!eventType) return;

  for (const queryKey of INVALIDATED_QUERY_KEYS) {
    void queryClient.invalidateQueries({ queryKey });
  }
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}
