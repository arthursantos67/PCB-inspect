"use client";

import { useEffect, useState } from "react";

/** Charts animate through a JS library, so the CSS `prefers-reduced-motion` override in
 * globals.css cannot reach them — they have to ask. Starts at `false` so the server render
 * and the first client render agree, then corrects on mount.
 */
export function usePrefersReducedMotion(): boolean {
  const [prefersReduced, setPrefersReduced] = useState(false);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    setPrefersReduced(query.matches);
    const onChange = (event: MediaQueryListEvent) => setPrefersReduced(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return prefersReduced;
}
