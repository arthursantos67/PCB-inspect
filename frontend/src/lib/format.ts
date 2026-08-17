import { currentLocale } from "@/lib/i18n/language-store";

/** One clock for the whole product. `toLocaleString()` with no options renders "8/16/2026,
 * 10:04:58 AM", which is dense, ambiguous between locales, and different from the "Aug 16,
 * 2026, 10:04 AM" every other screen shows. Times are read across screens (a board's
 * processed-at against a report's requested-at against an audit entry), so they are set the
 * same way everywhere.
 *
 * The locale follows the station language rather than the browser's, so switching to
 * Portuguese moves the dates too instead of leaving English months in a translated table.
 */
export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString(currentLocale(), {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/** Date without the clock, for the places that describe a span of days rather than a moment
 * (a report's period, for instance). Same locale rule as the timestamps above.
 */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(currentLocale(), { dateStyle: "medium" });
}

/** Clock only, for the chat bubbles, where every message is from today's session and the date
 * would repeat on every line. Same locale rule as the timestamps above.
 */
export function formatTimeOfDay(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleTimeString(currentLocale(), {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** The same clock with seconds, for the audit log, where entries land seconds apart and the
 * minute alone would show several identical rows.
 */
export function formatTimestampPrecise(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString(currentLocale(), {
    dateStyle: "medium",
    timeStyle: "medium",
  });
}
