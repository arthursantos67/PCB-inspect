/** Where the browser should reach the API.
 *
 * `NEXT_PUBLIC_*` variables are inlined into the bundle when `next build` runs, so on the
 * production image (frontend/Dockerfile) they are frozen at image-build time — an operator who
 * changes `API_PORT` in their `.env` would otherwise be talking to whatever port the image was
 * built against, with no way to fix it short of rebuilding. The root layout therefore reads the
 * variable on the server, per request, and publishes it to the page (see `app/layout.tsx`);
 * this reads that value first and falls back to the build-time one, which is what `next dev`
 * and the unit tests still supply.
 */

const DEFAULT_API_URL = "http://localhost:8000";

declare global {
  interface Window {
    __PCB_INSPECT_API_URL__?: string;
  }
}

export function apiUrl(): string {
  if (typeof window !== "undefined" && window.__PCB_INSPECT_API_URL__) {
    return window.__PCB_INSPECT_API_URL__;
  }
  return process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API_URL;
}

/** Server-side counterpart: the value the layout hands to the browser. Read at request time,
 * never captured in a module constant, so a restarted container picks up a changed `.env`.
 */
export function serverApiUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API_URL;
}
