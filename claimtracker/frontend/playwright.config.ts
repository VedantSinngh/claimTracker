import { defineConfig, devices } from "@playwright/test";

/**
 * The e2e spec drives a real browser against a real backend, so it needs both
 * servers up. Start them with `docker compose up` (or `npm run dev` plus
 * uvicorn) and point PLAYWRIGHT_BASE_URL at the frontend.
 */
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  // The claim pipeline is a background task, so the status assertions poll.
  expect: { timeout: 30_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
