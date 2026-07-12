import { defineConfig, devices } from "@playwright/test";

// NFR-08/section 14.2 — E2E against the running stack (frontend + API + a real Postgres/
// Redis + the inference worker). The worker runs with `INFERENCE_BACKEND=fake` in CI (no
// GPU, no `weights/best.pt`, see backend/app/inference/model.py) — this config only drives
// the browser side, the stack itself is brought up by the caller (see README/.github/
// workflows/ci.yml's `e2e` job).
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? "line" : "list",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
