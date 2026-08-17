import type { en } from "@/lib/i18n/en";

/** Every key the UI is allowed to ask for. Derived from the English dictionary, so a typo in a
 * `t(...)` call is a type error and `pt.ts` cannot silently go out of sync with it.
 */
export type TranslationKey = keyof typeof en;

export type TranslationParams = Record<string, string | number>;
