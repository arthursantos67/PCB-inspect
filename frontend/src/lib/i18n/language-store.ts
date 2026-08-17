// The station language (issue #50), mirrored out of React for the same reasons `auth-store`
// mirrors the session: the non-React api-client needs to read it on every request (so the API
// localizes analyses to what the operator is looking at), and localStorage lets the first
// paint after a reload already be in the right language instead of flashing English until
// `GET /settings/config` answers.
//
// The backend's `ui_language` config key is the source of truth; this is a cache of it.
// `I18nProvider` reconciles the two on mount and writes both on every switch.

export const LANGUAGES = ["en", "pt"] as const;

export type Language = (typeof LANGUAGES)[number];

export const DEFAULT_LANGUAGE: Language = "en";

const STORAGE_KEY = "pcb-inspect-language";

/** BCP 47 tags for `Intl`. Regional, not bare: `pt` alone leaves the date order and the month
 * abbreviations up to the runtime's default region, and this station is a Brazilian shop floor.
 */
const LOCALE: Record<Language, string> = { en: "en-US", pt: "pt-BR" };

export function localeFor(language: Language): string {
  return LOCALE[language] ?? LOCALE[DEFAULT_LANGUAGE];
}

/** The locale matching the language currently in force, for the non-React formatters in
 * `lib/format.ts` that have no context to read.
 */
export function currentLocale(): string {
  return localeFor(getLanguage());
}

export function isLanguage(value: unknown): value is Language {
  return typeof value === "string" && (LANGUAGES as readonly string[]).includes(value);
}

function loadPersistedLanguage(): Language {
  if (typeof window === "undefined") return DEFAULT_LANGUAGE;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return isLanguage(raw) ? raw : DEFAULT_LANGUAGE;
  } catch {
    return DEFAULT_LANGUAGE;
  }
}

let currentLanguage: Language = loadPersistedLanguage();
const listeners = new Set<() => void>();

export function getLanguage(): Language {
  return currentLanguage;
}

/** Stable across renders and always `DEFAULT_LANGUAGE`, so `useSyncExternalStore` doesn't
 * hydrate against a value the server could not have known.
 */
export function getServerLanguage(): Language {
  return DEFAULT_LANGUAGE;
}

export function setLanguage(next: Language): void {
  if (next === currentLanguage) return;
  currentLanguage = next;
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // localStorage unavailable (private browsing, quota exceeded) — the switch still holds
      // for this tab, it just won't be remembered on the next load.
    }
    document.documentElement.lang = next;
  }
  for (const listener of listeners) listener();
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
