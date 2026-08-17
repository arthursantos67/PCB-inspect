/** The station language switch (issue #50).
 *
 * The language is a station setting rather than a per-user one, because the Celery worker has
 * to read it when it writes an analysis with nobody logged in. That makes the switch a
 * three-way agreement between the screen, the persisted mirror and the API, and it is the
 * agreement that is worth testing: the operator sees the switch immediately, the API is told,
 * requests made afterwards ask for the new language, and a failed write never leaves the
 * screen stuck.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LanguageSwitcher } from "@/components/layout/LanguageSwitcher";
import { I18nProvider, translate, useI18n } from "@/contexts/I18nContext";
import { en } from "@/lib/i18n/en";
import { DEFAULT_LANGUAGE, getLanguage, setLanguage } from "@/lib/i18n/language-store";
import { pt } from "@/lib/i18n/pt";

vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return { ...actual, getConfig: vi.fn(), updateConfig: vi.fn() };
});

// Signed in: `I18nProvider` only reads the station setting back once there is a session to
// read it with.
vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ isAuthenticated: true }),
}));

const { getConfig, updateConfig } = await import("@/lib/api-client");

function Consumer() {
  const { t, language } = useI18n();
  return (
    <p>
      {language}: {t("nav.dashboard")}
    </p>
  );
}

function renderSwitcher() {
  return render(
    <I18nProvider>
      <Consumer />
      <LanguageSwitcher />
    </I18nProvider>
  );
}

beforeEach(() => {
  vi.mocked(getConfig).mockResolvedValue({ config: {} });
  vi.mocked(updateConfig).mockResolvedValue({ config: {} });
});

afterEach(() => {
  // The store is a module-level singleton by design (the non-React api-client reads it), so a
  // test that switched the language has to put it back. The persisted mirror is only read at
  // import time, so leaving it alone here cannot leak into the next test.
  setLanguage(DEFAULT_LANGUAGE);
  vi.clearAllMocks();
});

describe("station language", () => {
  it("starts in English on a station nobody has switched yet", async () => {
    renderSwitcher();

    expect(await screen.findByText("en: Dashboard")).toBeVisible();
  });

  it("switches every consumer at once and tells the API, so the worker agrees", async () => {
    renderSwitcher();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /português/i }));

    expect(await screen.findByText("pt: Painel")).toBeVisible();
    expect(screen.getByText("Idioma")).toBeVisible();
    expect(updateConfig).toHaveBeenCalledWith({ ui_language: "pt" });
  });

  it("adopts the language the station is already set to", async () => {
    vi.mocked(getConfig).mockResolvedValue({ config: { ui_language: "pt" } });

    renderSwitcher();

    expect(await screen.findByText("pt: Painel")).toBeVisible();
    // Reading the setting is not switching it: nothing is written back.
    expect(updateConfig).not.toHaveBeenCalled();
  });

  it("ignores a language this build has no dictionary for", async () => {
    vi.mocked(getConfig).mockResolvedValue({ config: { ui_language: "fr" } });

    renderSwitcher();

    expect(await screen.findByText("en: Dashboard")).toBeVisible();
  });

  it("keeps the switch when the write fails, since the operator already acted on it", async () => {
    vi.mocked(updateConfig).mockRejectedValue(new Error("offline"));
    renderSwitcher();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /português/i }));

    expect(await screen.findByText("pt: Painel")).toBeVisible();
  });

  it("tags the document, so the browser reads the page as Portuguese too", async () => {
    renderSwitcher();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /português/i }));

    await waitFor(() => expect(document.documentElement.lang).toBe("pt"));
  });

  it("marks the position in force, so the switch reads at a glance", async () => {
    renderSwitcher();
    const user = userEvent.setup();

    expect(screen.getByRole("button", { name: /english/i })).toHaveAttribute(
      "aria-pressed",
      "true"
    );

    await user.click(screen.getByRole("button", { name: /português/i }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /português/i })).toHaveAttribute(
        "aria-pressed",
        "true"
      )
    );
    expect(screen.getByRole("button", { name: /english/i })).toHaveAttribute(
      "aria-pressed",
      "false"
    );
  });

  it("reaches the API client, so analyses come back in the language on screen", async () => {
    renderSwitcher();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /português/i }));

    // `getInspection` reads the same store on every call (it is not a React consumer), which
    // is what makes the API localize the analysis prose to what the operator is looking at.
    await waitFor(() => expect(getLanguage()).toBe("pt"));
  });
});

describe("translation lookup", () => {
  it("fills placeholders in the string, not around it", () => {
    expect(translate("en", "common.pageOf", { page: 2, total: 7 })).toBe("Page 2 of 7");
    expect(translate("pt", "common.pageOf", { page: 2, total: 7 })).toBe("Página 2 de 7");
  });

  it("leaves a placeholder it was given nothing for visible rather than blank", () => {
    expect(translate("en", "common.pageOf", { page: 2 })).toBe("Page 2 of {total}");
  });

  it("falls back to English rather than rendering a key", () => {
    const dictionary = pt as Record<string, string>;
    const original = dictionary["nav.dashboard"];
    delete dictionary["nav.dashboard"];
    try {
      expect(translate("pt", "nav.dashboard")).toBe("Dashboard");
    } finally {
      dictionary["nav.dashboard"] = original;
    }
  });
});

describe("the dictionaries", () => {
  it("cover the same keys, so no screen is half-translated", () => {
    expect(Object.keys(pt).sort()).toEqual(Object.keys(en).sort());
  });

  it("have no empty strings, which would render as a missing label", () => {
    for (const [key, value] of Object.entries({ ...en, ...pt })) {
      expect(value.trim(), key).not.toBe("");
    }
  });

  it("never translate the defect class names", () => {
    // The classes are the names the model and the dataset use, and every other surface shows
    // them unchanged: the reports, the stored analyses and the chat answers. Translating them
    // on the screens alone would make the charts disagree with the report of the same board.
    const defectKeys = Object.keys(en).filter((key) => key.startsWith("defect."));
    expect(defectKeys).toHaveLength(6);
    for (const key of defectKeys) {
      expect(pt[key as keyof typeof pt], key).toBe(en[key as keyof typeof en]);
    }
  });
});
