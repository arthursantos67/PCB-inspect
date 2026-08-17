"use client";

import { useI18n } from "@/contexts/I18nContext";
import { LANGUAGES, type Language } from "@/lib/i18n/language-store";

const LABEL: Record<Language, string> = { en: "EN", pt: "PT" };
const FULL_LABEL: Record<Language, "shell.languageEnglish" | "shell.languagePortuguese"> = {
  en: "shell.languageEnglish",
  pt: "shell.languagePortuguese",
};

/** Two-position switch in the sidebar footer, next to the live-update lamp: the station's
 * language is a station setting like any other, and this is where the machine's own state is
 * already reported. Deliberately not a dropdown, since there are exactly two positions and an
 * operator should be able to hit the one they want without opening anything.
 */
export function LanguageSwitcher() {
  const { language, setLanguage, t } = useI18n();

  return (
    <div className="flex items-center justify-between gap-2 px-2">
      <span className="label-channel">{t("shell.language")}</span>
      <div
        role="group"
        aria-label={t("shell.language")}
        className="flex items-center gap-0.5 rounded-md bg-sidebar-accent/60 p-0.5"
      >
        {LANGUAGES.map((option) => {
          const active = option === language;
          return (
            <button
              key={option}
              type="button"
              onClick={() => setLanguage(option)}
              aria-pressed={active}
              title={t(FULL_LABEL[option])}
              className={`rounded px-1.5 py-0.5 font-mono text-[0.6875rem] tracking-[0.06em] transition-colors ${
                active
                  ? "bg-sidebar text-foreground shadow-panel"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {LABEL[option]}
              <span className="sr-only"> {t(FULL_LABEL[option])}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
