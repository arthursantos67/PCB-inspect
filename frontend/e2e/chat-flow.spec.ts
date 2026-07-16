import { randomUUID } from "node:crypto";
import { copyFileSync, mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { assertNoA11yViolations } from "./a11y";

// NFR-08 (section 14.2): the chat flow, end to end through the real UI (FR-09, FE-06). This
// job runs with no reachable LLM behind the seeded `llm.base_url` (backend/app/db/seed.py) —
// deliberately not mocked here, since UC-7's "LLM unavailable" alternative flow is exactly
// what a from-scratch CI environment (no LM Studio/Ollama running) naturally exercises: a
// graceful, persisted "temporarily unavailable" turn rather than a stuck or crashed request.
const DEV_ACCOUNT = { email: "dev@pcb-inspect.local", password: "devpassword123" };

test("starts a chat session, sends a message, and persists history across a reload", async ({
  page,
}) => {
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeEnabled();
  await page.getByLabel("Email").fill(DEV_ACCOUNT.email);
  await page.getByLabel("Password").fill(DEV_ACCOUNT.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL("/");

  // --- Open chat and start a new session (FE-06) ---
  await page.getByRole("link", { name: "Chat" }).click();
  await expect(page).toHaveURL("/chat");
  await assertNoA11yViolations(page, "Chat (empty)");

  await page.getByRole("button", { name: "New chat" }).first().click();
  await expect(page).toHaveURL(/\/chat\/.+/);
  await assertNoA11yViolations(page, "Chat session");

  // --- Send a message; streams incrementally via SSE, not one blocking request ---
  // Scoped to the conversation log — the session's sidebar title is derived from this same
  // first message (PRD 10.2), so an unscoped text query would match both.
  const conversation = page.getByRole("log", { name: "Conversation" });
  const input = page.getByLabel("Message");
  await input.fill("Which batches had the most defects this week?");
  await page.getByRole("button", { name: "Send" }).click();

  // No LLM reachable in this environment -> UC-7's graceful degradation, not a crash/hang.
  await expect(conversation.getByText("temporarily unavailable")).toBeVisible({ timeout: 15_000 });
  await expect(
    conversation.getByText("Which batches had the most defects this week?")
  ).toBeVisible();

  const sessionUrl = page.url();

  // --- History persists across a reload (issue #32's "History Persists" criterion) ---
  await page.reload();
  await expect(page).toHaveURL(sessionUrl);
  await expect(
    conversation.getByText("Which batches had the most defects this week?")
  ).toBeVisible();
  await expect(conversation.getByText("temporarily unavailable")).toBeVisible();
});

test("opens a scoped chat session from an analysis detail screen", async ({ page }) => {
  // Self-contained ingestion (mirrors e2e/inspection-flow.spec.ts) rather than depending on
  // another spec file having already produced a completed inspection first — spec files must
  // not depend on execution order.
  const boardNumber = `chat-scope-${randomUUID().slice(0, 8)}`;
  const watchDir = mkdtempSync(path.join(tmpdir(), "pcb-inspect-e2e-chat-"));
  const batchDir = path.join(watchDir, `BATCH-CHAT-${randomUUID().slice(0, 8)}`);
  mkdirSync(batchDir);
  copyFileSync(
    path.join(__dirname, "fixtures", "board.jpg"),
    path.join(batchDir, `${boardNumber}.jpg`)
  );

  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeEnabled();
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

  // Baseline analysis (FR-06) is always available once processing completes, regardless of
  // whether the in-depth agent chain also ran — so the entry point is reliably present here.
  const askButton = page.getByRole("button", { name: "Ask about this analysis" });
  await expect(askButton).toBeVisible({ timeout: 30_000 });
  await askButton.click();

  // FE-03's entry point: a new session pre-scoped to this inspection, with no re-typed context.
  await expect(page).toHaveURL(/\/chat\/.+/);
  await assertNoA11yViolations(page, "Chat session scoped to an analysis");
});
