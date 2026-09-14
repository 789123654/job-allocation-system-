import { browser, expect } from "@wdio/globals";

// Phase 6 Step 1 — harness-proving only (see the plan's "Explicit checkpoint" section): this spec
// exists to prove the WebdriverIO + @wdio/tauri-service + embedded-WebDriver harness itself works
// against the real packaged app, driven through real UI, against the real local
// Supabase+FastAPI stack the CI e2e job already stands up (.github/workflows/ci.yml) — not to add
// new business-logic coverage yet. Turns the Phase 4 Step 1 plan's own manual verification steps
// ("log in... reaches the authenticated placeholder route, not the gate... session persists")
// into an automated one.
//
// Credentials come from the CI job's existing "Seed a real owner account for the frontend
// contract test" step (E2E_OWNER_EMAIL/E2E_OWNER_PASSWORD) — the same seeded row the contract
// test already uses via its bearer token, not a second insert.
const email = process.env.E2E_OWNER_EMAIL;
const password = process.env.E2E_OWNER_PASSWORD;

describe("Login flow", () => {
  it("logs in a real owner account, lands on the Owner Dashboard, and persists the session across a reload", async () => {
    if (!email || !password) {
      throw new Error("E2E_OWNER_EMAIL / E2E_OWNER_PASSWORD must be set — see ci.yml's e2e job.");
    }

    const emailInput = await browser.$("#email");
    await emailInput.waitForDisplayed();
    await emailInput.setValue(email);

    const passwordInput = await browser.$("#password");
    await passwordInput.setValue(password);

    const submitButton = await browser.$('button[type="submit"]');
    await submitButton.click();

    // Seeded with must_change_password = false — a real owner account with a password already
    // set must reach the authenticated shell directly, never the forced-reset gate
    // (router.tsx's mustChangePassword check, ARCHITECTURE.md §4 / FRONTEND_ARCHITECTURE.md §6).
    const heading = await browser.$("h1=Dashboard");
    await heading.waitForDisplayed({ timeout: 15000 });
    await expect(heading).toHaveText("Dashboard");
    await expect(browser).not.toHaveUrl(/set-new-password/);

    // Session persistence — session-store.tsx's getSession() must round-trip through the real
    // Tauri store (DPAPI-encrypted on Windows, plaintext passthrough elsewhere per
    // store_crypto.rs) on a fresh module load, not just survive in live JS memory.
    await browser.refresh();
    const headingAfterReload = await browser.$("h1=Dashboard");
    await headingAfterReload.waitForDisplayed({ timeout: 15000 });
    await expect(headingAfterReload).toHaveText("Dashboard");
  });
});
