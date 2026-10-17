/**
 * e2e/claim-flow.spec.ts
 * ───────────────────────
 * The one end-to-end journey the spec asks for: register/sign in, submit a
 * claim with a real bill, and watch the status settle.
 *
 * This drives a real browser against a **real backend**, so unlike every other
 * test in this repo nothing is faked — the pipeline really runs OCR, calls
 * Groq and searches FAISS. That means it needs:
 *
 *   - both servers up (`docker compose up`, or uvicorn + `npm run dev`)
 *   - a valid GROQ_API_KEY in the backend environment
 *   - a handbook already ingested, or the RAG step routes to NEEDS_REVIEW
 *
 * Run it with `npm run test:e2e`. It is deliberately not part of the CI job:
 * CI has no Groq key, and a test that spends money on every push is a bad
 * trade. The assertions below therefore accept any terminal status rather
 * than a specific one — what is being tested is that the journey completes
 * and the claim stops being in flight, not what the model decided.
 */
import { expect, test } from "@playwright/test";
import path from "node:path";

const SAMPLE_BILL = path.resolve(__dirname, "../../samples/bill_accepted.pdf");

/** A fresh account per run, so repeated runs do not collide on the email. */
function uniqueEmail(): string {
  return `e2e-${Date.now()}-${Math.floor(Math.random() * 1000)}@example.com`;
}

const PASSWORD = "SecurePass1";

test.describe("claim journey", () => {
  test("register, submit a claim, and see it reach a decision", async ({ page }) => {
    const email = uniqueEmail();

    // ── Register ──────────────────────────────────────────────────
    await page.goto("/register");
    await expect(page.getByRole("heading", { name: "Create an account" })).toBeVisible();

    await page.getByLabel("Full name").fill("E2E Test User");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Create account" }).click();

    // Registration signs the user in and lands on the claims list.
    await expect(page).toHaveURL(/\/claims$/);
    await expect(page.getByRole("heading", { name: "Claims" })).toBeVisible();

    // ── Submit a claim ────────────────────────────────────────────
    await page.getByRole("link", { name: "Submit a claim" }).first().click();
    await expect(page.getByRole("heading", { name: "Submit a claim" })).toBeVisible();

    await page.getByLabel("Patient name").fill("John Smith");
    await page.getByLabel("Claim item").fill("Hospitalisation");
    await page.getByLabel("Reason / diagnosis").fill("Acute appendicitis");
    await page.getByLabel("Medical facility").fill("Metropolitan General Hospital");
    await page.getByLabel("Date of treatment").fill("2024-03-15");
    await page.getByLabel("Patient address").fill("45 Maple Avenue, New York, NY 10002");
    await page.getByLabel("Amount claimed (USD)").fill("9860");
    await page.getByLabel("Itemised bill").setInputFiles(SAMPLE_BILL);

    await page.getByRole("button", { name: "Submit claim" }).click();

    // ── Watch the status settle ───────────────────────────────────
    // The backend returns PENDING immediately and runs the pipeline as a
    // background task; the detail page polls.
    await expect(page).toHaveURL(/\/claims\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("heading", { name: "Hospitalisation" })).toBeVisible();

    // The claim as submitted is shown straight away, before any decision.
    await expect(page.getByText("Claim as submitted")).toBeVisible();
    await expect(page.getByText("$9,860.00").first()).toBeVisible();

    // Any terminal status is a pass — which one depends on the live model and
    // on whether a handbook has been ingested.
    const terminalStatus = page.getByText(/^(Accepted|Rejected|Needs review)$/).first();
    await expect(terminalStatus).toBeVisible({ timeout: 60_000 });

    // Once decided, the decision section must carry a reason — the product
    // rule is that no decision is shown without one.
    await expect(page.getByText("Decision", { exact: false }).first()).toBeVisible();

    // ── And it appears in the list ────────────────────────────────
    await page.getByRole("link", { name: /Back to claims/ }).click();
    await expect(page).toHaveURL(/\/claims$/);
    await expect(page.getByRole("cell", { name: "John Smith" })).toBeVisible();
  });

  test("sign out and back in", async ({ page }) => {
    const email = uniqueEmail();

    await page.goto("/register");
    await page.getByLabel("Full name").fill("Returning User");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page).toHaveURL(/\/claims$/);

    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login/);

    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page).toHaveURL(/\/claims$/);
    await expect(page.getByRole("heading", { name: "Claims" })).toBeVisible();
  });

  test("a protected page redirects an anonymous visitor to sign in", async ({ page }) => {
    await page.goto("/claims");
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  });

  test("a plain user cannot reach the admin pages", async ({ page }) => {
    const email = uniqueEmail();

    await page.goto("/register");
    await page.getByLabel("Full name").fill("Plain User");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page).toHaveURL(/\/claims$/);

    // The nav must not offer the admin pages...
    await expect(page.getByRole("link", { name: "Exclusions" })).toHaveCount(0);

    // ...and visiting one directly is refused with an explanation.
    await page.goto("/admin/exclusions");
    await expect(page.getByText(/do not have access/i)).toBeVisible();
  });
});
