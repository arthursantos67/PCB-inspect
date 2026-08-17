/** Dates follow the station language, not the browser's (issue #50): a translated table with
 * English month abbreviations in it is still an English screen, and this station is a
 * Brazilian shop floor, so `pt` means `pt-BR` rather than whatever region the runtime picks.
 */

import { afterEach, describe, expect, it } from "vitest";

import { formatDate, formatTimestamp } from "@/lib/format";
import { DEFAULT_LANGUAGE, currentLocale, setLanguage } from "@/lib/i18n/language-store";

const MOMENT = "2026-08-16T14:30:00Z";

afterEach(() => {
  setLanguage(DEFAULT_LANGUAGE);
});

describe("timestamps", () => {
  it("resolves the language to a region, so the date order is not left to the runtime", () => {
    expect(currentLocale()).toBe("en-US");
    setLanguage("pt");
    expect(currentLocale()).toBe("pt-BR");
  });

  it("renders in the language the station is set to", () => {
    const english = formatDate(MOMENT);
    setLanguage("pt");
    const portuguese = formatDate(MOMENT);

    expect(english).toMatch(/Aug/);
    expect(portuguese).toMatch(/ago/);
  });

  it("shows a dash rather than an Invalid Date for a board that has not got there yet", () => {
    expect(formatTimestamp(null)).toBe("—");
    expect(formatDate(undefined)).toBe("—");
  });
});
