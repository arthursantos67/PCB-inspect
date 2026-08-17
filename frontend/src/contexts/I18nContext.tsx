"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useSyncExternalStore } from "react";

import { useAuth } from "@/contexts/AuthContext";
import { getConfig, updateConfig } from "@/lib/api-client";
import { en } from "@/lib/i18n/en";
import {
  DEFAULT_LANGUAGE,
  getLanguage,
  getServerLanguage,
  isLanguage,
  type Language,
  setLanguage as setStoredLanguage,
  subscribe,
} from "@/lib/i18n/language-store";
import { pt } from "@/lib/i18n/pt";
import type { TranslationKey, TranslationParams } from "@/lib/i18n/types";

const DICTIONARIES: Record<Language, Record<TranslationKey, string>> = { en, pt };

/** `ui_language` is a station setting, not a per-user preference (the Celery worker has to be
 * able to read it when it writes an analysis), so switching the language here writes it back
 * to the API for every screen and every future analysis to pick up.
 */
const LANGUAGE_CONFIG_KEY = "ui_language";

export type Translate = (key: TranslationKey, params?: TranslationParams) => string;

type I18nContextValue = {
  language: Language;
  setLanguage: (language: Language) => void;
  t: Translate;
};

const I18nContext = createContext<I18nContextValue | null>(null);

/** Substitutes `{name}` placeholders. A missing key falls back to the English string and then
 * to the key itself, so a half-translated screen degrades to readable English rather than to
 * a blank button.
 */
export function translate(
  language: Language,
  key: TranslationKey,
  params?: TranslationParams
): string {
  const template = DICTIONARIES[language]?.[key] ?? en[key] ?? key;
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in params ? String(params[name]) : match
  );
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const language = useSyncExternalStore(subscribe, getLanguage, getServerLanguage);
  const { isAuthenticated } = useAuth();

  // The API is the source of truth, so an operator who switched the station to Portuguese on
  // the other machine sees Portuguese here too. Read once per sign-in rather than on a query
  // cache: the setting changes about as often as the hardware does.
  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;
    void getConfig()
      .then(({ config }) => {
        const stored = config[LANGUAGE_CONFIG_KEY];
        if (!cancelled && isLanguage(stored)) setStoredLanguage(stored);
      })
      .catch(() => {
        // Offline or not yet authorized: the persisted language is a perfectly good answer.
      });
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  const setLanguage = useCallback((next: Language) => {
    // Applied locally first: the operator sees the switch immediately, and the write below is
    // what makes it stick for the worker and the next session. A failed write leaves this tab
    // translated and logs nothing the operator can act on, so it is deliberately silent.
    setStoredLanguage(next);
    void updateConfig({ [LANGUAGE_CONFIG_KEY]: next }).catch(() => {});
  }, []);

  const value = useMemo<I18nContextValue>(
    () => ({
      language,
      setLanguage,
      t: (key, params) => translate(language, key, params),
    }),
    [language, setLanguage]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

const FALLBACK: I18nContextValue = {
  language: DEFAULT_LANGUAGE,
  setLanguage: () => {},
  t: (key, params) => translate(DEFAULT_LANGUAGE, key, params),
};

/** Outside a provider (a component rendered on its own in a unit test) this answers in the
 * default language instead of throwing, so a test that only cares about a component's
 * behaviour doesn't have to wrap it.
 */
export function useI18n(): I18nContextValue {
  return useContext(I18nContext) ?? FALLBACK;
}
