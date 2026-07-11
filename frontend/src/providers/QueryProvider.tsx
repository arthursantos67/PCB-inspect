"use client";

import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

export function QueryProvider({ children }: { children: React.ReactNode }) {
  // Created once per mount (not per render) so query state survives re-renders but never
  // leaks between separate app instances (relevant if this ever runs under React Strict
  // Mode's double-invoke or, later, SSR).
  const [queryClient] = useState(() => new QueryClient());

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
