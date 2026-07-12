import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

// Issue #24 (FE-10): shared helper so every Phase-1 screen gets the same automated contrast/
// ARIA/labeling scan. Scoped to the WCAG 2.1 A/AA rule set (not "best-practice" rules like
// heading-order) so this stays a real regression guard rather than a check that drifts with
// axe-core's evolving best-practice opinions. Fails only on critical/serious violations — the
// acceptance criterion (AC2) is "no critical violations"; serious ones (most WCAG AA failures
// surface as "serious", not "critical") are included too since letting those slide would make
// this check nearly meaningless in practice.
export async function assertNoA11yViolations(page: Page, screenName: string) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const blocking = results.violations.filter(
    (violation) => violation.impact === "critical" || violation.impact === "serious"
  );

  if (blocking.length > 0) {
    const details = blocking
      .map(
        (violation) =>
          `\n- [${violation.impact}] ${violation.id}: ${violation.help} (${violation.nodes.length} node(s))\n  ${violation.nodes
            .map((node) => node.target.join(" "))
            .join("\n  ")}`
      )
      .join("");
    throw new Error(`Accessibility violations on ${screenName}:${details}`);
  }

  expect(blocking).toEqual([]);
}
