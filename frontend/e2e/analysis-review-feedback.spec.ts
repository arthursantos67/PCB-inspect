import { randomUUID } from "node:crypto";
import { copyFileSync, mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { assertNoA11yViolations } from "./a11y";

// FR-10 / Issue 33: analysis validation, per-detection feedback, board disposition, and
// manual annotation, driven through the real UI against the fake-inference-backend pipeline
// (see inspection-flow.spec.ts for why that keeps this deterministic without a GPU).
const DEV_ACCOUNT = { email: "dev@pcb-inspect.local", password: "devpassword123" };

test("validates an analysis, gives detection feedback, sets disposition, and manually annotates a missed defect", async ({
  page,
}) => {
  const boardNumber = `review-e2e-${randomUUID().slice(0, 8)}`;
  const batchNumber = `REVIEW-${randomUUID().slice(0, 8)}`;
  const watchDir = mkdtempSync(path.join(tmpdir(), "pcb-inspect-e2e-review-"));
  const batchDir = path.join(watchDir, batchNumber);
  mkdirSync(batchDir);
  copyFileSync(path.join(__dirname, "fixtures", "board.jpg"), path.join(batchDir, `${boardNumber}.jpg`));

  // --- Log in, ingest, and open the board's detail screen (see inspection-flow.spec.ts) ---
  await page.goto("/login");
  await page.getByLabel("Email").fill(DEV_ACCOUNT.email);
  await page.getByLabel("Password").fill(DEV_ACCOUNT.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL("/");

  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page).toHaveURL("/settings/ingestion");
  await page.getByLabel("Directory to scan").fill(watchDir);
  await page.getByRole("button", { name: "Scan directory now" }).click();
  await expect(page.getByText("Discovered 1 · Ingested 1 · Duplicate 0 · Failed 0 · Skipped 0")).toBeVisible();

  await page.getByRole("link", { name: "Dashboard" }).click();
  await expect(page).toHaveURL("/");
  const row = page.getByRole("row", { name: new RegExp(boardNumber) });
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.getByRole("link", { name: boardNumber }).click();
  await expect(page).toHaveURL(/\/inspections\/.+/);
  await expect(page.getByText("Processing", { exact: true })).toHaveCount(0, { timeout: 30_000 });
  await assertNoA11yViolations(page, "Inspection detail (before review)");

  // --- Detection Feedback: confirm the fake backend's deterministic "short" detection ---
  const detectionsList = page.getByRole("list", { name: "Detected defects" });
  await expect(detectionsList.getByText("Short")).toBeVisible();
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(detectionsList.getByText("Feedback: Confirmed")).toBeVisible();

  // --- Review Recorded: validate the analysis with a comment ---
  await page.getByLabel("Comment (optional)").fill("Looks correct.");
  await page.getByRole("button", { name: "Validate" }).click();
  await expect(page.getByText("Review status: Validated")).toBeVisible();
  await expect(page.getByText(/validated · .* — Looks correct\./)).toBeVisible();

  // --- Disposition Recorded: set the board's final disposition ---
  await page.getByLabel("Disposition").selectOption("approved");
  await expect(page.getByLabel("Disposition")).toHaveValue("approved");

  // --- Disposition shows on search results too (Issue 8's filter list) ---
  await page.getByRole("link", { name: "Inspections" }).click();
  await expect(page).toHaveURL("/inspections");
  const searchRow = page.getByRole("row", { name: new RegExp(boardNumber) });
  await expect(searchRow).toBeVisible({ timeout: 30_000 });
  await expect(searchRow.getByText("Approved")).toBeVisible();

  // --- Manual Annotation: draw a bbox + class via the keyboard-only numeric-input path
  // (FE-10, Issue 24) — no pointer drag involved, proving the non-pointer path works ---
  await searchRow.getByRole("link", { name: boardNumber }).click();
  await expect(page).toHaveURL(/\/inspections\/.+/);

  await page.getByRole("button", { name: "Annotate missed defect" }).focus();
  await page.keyboard.press("Enter");

  await page.getByLabel("Defect type").selectOption("spurious_copper");
  await page.getByLabel("X1 (%)").fill("10");
  await page.getByLabel("Y1 (%)").fill("10");
  await page.getByLabel("X2 (%)").fill("40");
  await page.getByLabel("Y2 (%)").fill("40");

  const addAnnotationButton = page.getByRole("button", { name: "Add annotation" });
  await expect(addAnnotationButton).toBeEnabled();
  await addAnnotationButton.focus();
  await page.keyboard.press("Enter");

  await expect(detectionsList.getByText("Spurious copper")).toBeVisible();
  await expect(detectionsList.getByText("Manual", { exact: true })).toBeVisible();
  await expect(detectionsList.getByText("Manually annotated")).toBeVisible();

  await assertNoA11yViolations(page, "Inspection detail (after review/annotation)");
});
