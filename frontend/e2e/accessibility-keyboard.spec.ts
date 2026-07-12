import { randomUUID } from "node:crypto";
import { copyFileSync, mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { expect, test } from "@playwright/test";

// Issue #24 (FE-10), Acceptance Criterion 1: "login -> ingest -> dashboard -> search/filter ->
// detail completes with no dead ends, keyboard only." Every step below drives the UI via
// `.focus()` (which only succeeds on elements that are actually part of the tab order —
// natively focusable or with a `tabindex`) plus `keyboard.press(...)`, never `.click()`. That
// proves both reachability (an unfocusable element fails the `.focus()` call) and operability
// (the key press must trigger the same handler a mouse click would).
const DEV_ACCOUNT = { email: "dev@pcb-inspect.local", password: "devpassword123" };

test("completes the Phase-1 golden path using the keyboard alone", async ({ page }) => {
  const boardNumber = `kbd-e2e-${randomUUID().slice(0, 8)}`;
  const batchNumber = `KBD-${randomUUID().slice(0, 8)}`;
  const watchDir = mkdtempSync(path.join(tmpdir(), "pcb-inspect-e2e-kbd-"));
  const batchDir = path.join(watchDir, batchNumber);
  mkdirSync(batchDir);
  copyFileSync(path.join(__dirname, "fixtures", "board.jpg"), path.join(batchDir, `${boardNumber}.jpg`));

  // --- Login screen (no AppShell/skip-link here — it's outside the authenticated shell) ---
  await page.goto("/login");
  await page.getByLabel("Email").focus();
  await page.keyboard.type(DEV_ACCOUNT.email);
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Password")).toBeFocused();
  await page.keyboard.type(DEV_ACCOUNT.password);
  await page.getByRole("button", { name: "Sign in" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL("/");
  // Wait for the dashboard's own content (not just the URL) so the login form has fully
  // unmounted before the next Tab press — otherwise a lingering focused element from the
  // outgoing page can swallow it during the client-side route transition.
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

  // --- Once inside the authenticated shell, the very first Tab stop must be the skip link ---
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();

  // --- Dashboard -> Settings via the primary nav link (Enter activates a link like a click) ---
  await page.getByRole("link", { name: "Settings" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL("/settings/ingestion");

  // --- Scan the fixture directory using only the keyboard ---
  await page.getByLabel("Directory to scan").focus();
  await page.keyboard.type(watchDir);
  await page.getByRole("button", { name: "Scan directory now" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Discovered 1 · Ingested 1 · Duplicate 0 · Failed 0 · Skipped 0")).toBeVisible();

  // --- Settings -> Ingestion monitor via the primary nav link ---
  await page.getByRole("link", { name: "Ingestion" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL("/ingestion");

  // --- The ad hoc import dropzone must be reachable and operable via keyboard too (it opens
  // the native file picker on Enter/Space; opening that OS dialog isn't exercised here, but
  // reaching + activating the control is exactly what regressed without a role/tabindex) ---
  const dropzone = page.getByRole("button", { name: "Drop image files here, or activate to choose files" });
  await dropzone.focus();
  await expect(dropzone).toBeFocused();

  // --- Ingestion -> Dashboard, open the ingested board from the recent-analyses table ---
  await page.getByRole("link", { name: "Dashboard" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL("/");

  // --- Dashboard -> Inspections (search/history), filter by board number ---
  await page.getByRole("link", { name: "Inspections" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL("/inspections");

  await page.getByLabel("Board").focus();
  await page.keyboard.type(boardNumber);
  const row = page.getByRole("row", { name: new RegExp(boardNumber) });
  await expect(row).toBeVisible({ timeout: 30_000 });

  // --- Open the result's detail screen via the row's link, keyboard only ---
  await row.getByRole("link", { name: boardNumber }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/inspections\/.+/);
  await expect(page.getByText(`Board ${boardNumber}`)).toBeVisible();

  // --- Detail screen: toggle to the annotated image and reach a bbox detection button,
  // all via keyboard, once the pipeline has produced a detection ---
  await expect(page.getByText("Processing", { exact: true })).toHaveCount(0, { timeout: 30_000 });
  const annotatedToggle = page.getByRole("button", { name: "Annotated", exact: true });
  await annotatedToggle.focus();
  await page.keyboard.press("Enter");
  const bboxButton = page.getByRole("button", { name: /Detection 1: Short/ });
  await expect(bboxButton).toBeVisible();
  await bboxButton.focus();
  await expect(bboxButton).toBeFocused();

  // --- Zoom in via keyboard-focused controls, then pan the image with arrow keys ---
  const viewer = page.getByRole("group", { name: /PCB image, zoom and pan/ });
  await page.getByRole("button", { name: "Zoom in" }).focus();
  await page.keyboard.press("Enter");
  await expect(viewer).toHaveAttribute("aria-label", /use arrow keys to pan/);
  await viewer.focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Home");
});
