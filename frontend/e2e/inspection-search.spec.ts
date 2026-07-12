import { randomUUID } from "node:crypto";
import { copyFileSync, mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { assertNoA11yViolations } from "./a11y";

// FE-04: the dedicated search/history screen at /inspections, backed by the same search API
// as Issue 8 (GET /api/v1/inspections). Ingests two boards in one scan so a board-number
// filter has something real to narrow down, then exercises: filtering alone, filtering
// combined with a second criterion, the empty state, URL shareability (survives a reload),
// clearing filters, and opening a result's detail screen.
const DEV_ACCOUNT = { email: "dev@pcb-inspect.local", password: "devpassword123" };

test("filters the inspections list, combined and alone, with shareable URL state", async ({ page }) => {
  const suffix = randomUUID().slice(0, 8);
  const boardA = `search-a-${suffix}`;
  const boardB = `search-b-${suffix}`;
  const watchDir = mkdtempSync(path.join(tmpdir(), "pcb-inspect-e2e-search-"));
  const batchADir = path.join(watchDir, `BATCH-A-${suffix}`);
  const batchBDir = path.join(watchDir, `BATCH-B-${suffix}`);
  mkdirSync(batchADir);
  mkdirSync(batchBDir);
  copyFileSync(path.join(__dirname, "fixtures", "board.jpg"), path.join(batchADir, `${boardA}.jpg`));
  copyFileSync(path.join(__dirname, "fixtures", "board.jpg"), path.join(batchBDir, `${boardB}.jpg`));

  // --- Log in and ingest both boards in a single scan (UC-1, FR-03) ---
  await page.goto("/login");
  await page.getByLabel("Email").fill(DEV_ACCOUNT.email);
  await page.getByLabel("Password").fill(DEV_ACCOUNT.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL("/");

  await page.getByRole("link", { name: "Ingestion" }).click();
  await expect(page).toHaveURL("/ingestion");
  await page.getByLabel("Directory to scan").fill(watchDir);
  await page.getByRole("button", { name: "Scan directory now" }).click();
  await expect(page.getByText("Discovered 2 · Ingested 2 · Duplicate 0 · Failed 0 · Skipped 0")).toBeVisible();

  // --- Navigate to the search/history screen via the nav entry (not a raw goto) ---
  await page.getByRole("link", { name: "Inspections" }).click();
  await expect(page).toHaveURL("/inspections");
  await assertNoA11yViolations(page, "Inspections search/history");

  const rowA = page.getByRole("row", { name: new RegExp(boardA) });
  const rowB = page.getByRole("row", { name: new RegExp(boardB) });
  await expect(rowA).toBeVisible({ timeout: 30_000 });
  await expect(rowB).toBeVisible();

  // --- Board filter alone narrows to a single result and updates the URL (shareable) ---
  await page.getByLabel("Board").fill(boardA);
  await expect(page).toHaveURL(new RegExp(`board_number=${boardA}`), { timeout: 5_000 });
  await expect(rowA).toBeVisible();
  await expect(rowB).toHaveCount(0);

  // --- Combined with defect type: the fake worker deterministically reports a "short"
  // defect (see inspection-flow.spec.ts), so board + defect_type=short still matches ---
  await page.getByRole("checkbox", { name: "Short" }).click();
  await expect(page).toHaveURL(/defect_type=short/);
  await expect(rowA).toBeVisible({ timeout: 30_000 });

  // --- Swapping to a defect type that was never detected empties the combined result ---
  await page.getByRole("checkbox", { name: "Short" }).click();
  await page.getByRole("checkbox", { name: "Missing hole" }).click();
  await expect(page.getByText("No inspections match these filters.")).toBeVisible();

  // --- A hard reload wipes the in-memory session by design (FE-01/section 13 — never
  // localStorage) and bounces through /login?next=..., but the filtered URL itself must
  // survive that round trip and land back with every filter restored (FE-04 shareability) ---
  const filteredUrl = page.url();
  await page.reload();
  await expect(page).toHaveURL(/\/login\?next=/);
  await page.getByLabel("Email").fill(DEV_ACCOUNT.email);
  await page.getByLabel("Password").fill(DEV_ACCOUNT.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(filteredUrl);
  await expect(page.getByLabel("Board")).toHaveValue(boardA);
  await expect(page.getByRole("checkbox", { name: "Missing hole" })).toBeChecked();
  await expect(page.getByText("No inspections match these filters.")).toBeVisible();

  // --- Clearing filters restores the full result set ---
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(page).toHaveURL("/inspections");
  await expect(rowA).toBeVisible();
  await expect(rowB).toBeVisible();

  // --- Selecting a result opens the existing analysis detail screen (Issue 10) ---
  await rowA.getByRole("link", { name: boardA }).click();
  await expect(page).toHaveURL(/\/inspections\/.+/);
  await expect(page.getByText(`Board ${boardA}`)).toBeVisible();
});
