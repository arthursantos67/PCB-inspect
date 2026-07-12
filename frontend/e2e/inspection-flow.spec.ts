import { randomUUID } from "node:crypto";
import { copyFileSync, mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { assertNoA11yViolations } from "./a11y";

// NFR-08 (section 14.2): directory ingestion -> processing -> viewing the completed
// analysis, end to end through the real UI. Uses the dev seed account (backend/app/db/
// seed.py) and the `INFERENCE_BACKEND=fake` worker (see playwright.config.ts) so the
// pipeline completes deterministically without `weights/best.pt` or a GPU.
const DEV_ACCOUNT = { email: "dev@pcb-inspect.local", password: "devpassword123" };

test("ingests a board, processes it, and renders the completed analysis", async ({ page }) => {
  const boardNumber = "board-e2e";
  const batchNumber = `E2E-${randomUUID().slice(0, 8)}`;
  const watchDir = mkdtempSync(path.join(tmpdir(), "pcb-inspect-e2e-"));
  const batchDir = path.join(watchDir, batchNumber);
  mkdirSync(batchDir);
  copyFileSync(path.join(__dirname, "fixtures", "board.jpg"), path.join(batchDir, `${boardNumber}.jpg`));

  // --- Log in with the seeded dev account (UC-1) ---
  await page.goto("/login");
  // The submit button starts disabled until `getSetupStatus()` resolves (setupRequired is
  // briefly null) — wait for that settled state before scanning, otherwise the transient
  // disabled-button contrast is a race, not a real finding.
  await expect(page.getByRole("button", { name: "Sign in" })).toBeEnabled();
  await assertNoA11yViolations(page, "Login");
  await page.getByLabel("Email").fill(DEV_ACCOUNT.email);
  await page.getByLabel("Password").fill(DEV_ACCOUNT.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL("/");
  await assertNoA11yViolations(page, "Dashboard");

  // --- Trigger a one-off directory scan of the fixture batch (FR-03, FE-05, UC-2) ---
  await page.getByRole("link", { name: "Ingestion" }).click();
  await expect(page).toHaveURL("/ingestion");
  await assertNoA11yViolations(page, "Ingestion");
  await page.getByLabel("Directory to scan").fill(watchDir);
  await page.getByRole("button", { name: "Scan directory now" }).click();
  await expect(page.getByText("Discovered 1 · Ingested 1 · Duplicate 0 · Failed 0 · Skipped 0")).toBeVisible();

  // --- Open the ingested board from the dashboard's recent-analyses table (UC-5) ---
  await page.getByRole("link", { name: "Dashboard" }).click();
  await expect(page).toHaveURL("/");
  const row = page.getByRole("row", { name: new RegExp(boardNumber) });
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.getByRole("link", { name: boardNumber }).click();
  await expect(page).toHaveURL(/\/inspections\/.+/);

  // --- Detail screen starts in a processing state and updates live via SSE (no refresh) ---
  await expect(page.getByText("Processing", { exact: true })).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByText("Analysis", { exact: true })).toBeVisible();
  await assertNoA11yViolations(page, "Inspection detail");

  // --- Detections panel synced with the fake backend's deterministic "short" defect ---
  const detectionsList = page.getByRole("list", { name: "Detected defects" });
  await expect(detectionsList.getByText("Short")).toBeVisible();

  // --- Annotated viewer: toggle works, numbered bbox renders and aligns with the detection ---
  const annotatedToggle = page.getByRole("button", { name: "Annotated", exact: true });
  await expect(annotatedToggle).toBeEnabled();
  await annotatedToggle.click();
  await expect(page.getByRole("button", { name: /Detection 1: Short/ })).toBeVisible();

  // --- Baseline analysis content renders (FR-06) ---
  await expect(page.getByText("Probable causes:")).toBeVisible();
  await expect(page.getByText("Suggested solutions:")).toBeVisible();
});
