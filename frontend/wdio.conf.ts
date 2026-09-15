// Phase 6 Step 1 E2E harness (docs/CODING_STRUCTURE.md §4, FRONTEND_ARCHITECTURE.md §9). Config
// shape follows tauri-official/chapters/testing.md and @wdio/tauri-service's own quick-start
// guide directly (verified live against the source repo this session, not guessed) — deliberately
// the plain single-app shape from that guide, not the desktop-mobile monorepo's own internal
// multiremote/deeplink/splash test-harness config, which this project doesn't need.
//
// Runs against the debug binary built by the CI e2e job's own
// `cargo tauri build --debug --features e2e-testing --config src-tauri/tauri.e2e.conf.json` step
// — never a release build, so the wdio-webdriver capability this depends on is only ever present
// here, not in anything actually distributed (Cargo.toml's own comment explains why).
import { browser } from "@wdio/globals";

export const config: WebdriverIO.Config = {
  runner: "local",
  specs: ["./e2e/specs/**/*.spec.ts"],
  // A single embedded WebDriver server backs one running app instance — sequential specs avoid
  // two app processes racing over the same local Postgres/Supabase-backed owner account.
  maxInstances: 1,

  capabilities: [
    {
      browserName: "tauri",
      "tauri:options": {
        application: "./src-tauri/target/debug/app",
      },
    },
  ],

  services: [
    [
      "@wdio/tauri-service",
      {
        appBinaryPath: "./src-tauri/target/debug/app",
        driverProvider: "embedded",
        // Temporary — re-added 2026-09-15 to diagnose a second, different failure once the
        // startup-crash bug (xvfb-run fix) was resolved: the webview's Tauri JS bridge never
        // becomes ready (`core.invoke` times out) and #email never renders. Need the app's own
        // stdout/stderr (tauri_plugin_log output) to see what the frontend is actually doing.
        // Remove once this second issue is root-caused.
        captureBackendLogs: true,
      },
    ],
  ],

  logLevel: "info",
  bail: 0,
  baseUrl: "",
  waitforTimeout: 10000,
  connectionRetryTimeout: 120000,
  connectionRetryCount: 3,

  framework: "mocha",
  reporters: ["spec"],
  mochaOpts: {
    ui: "bdd",
    timeout: 60000,
  },

  // Temporary — added 2026-09-15 to diagnose why the webview's Tauri JS bridge (core.invoke) never
  // becomes ready (#email never renders) even after fixing the earlier startup crash and the
  // WebKitGTK/DRI3 software-rendering issue. Prints straight to this job's own stdout (unlike
  // captureBackendLogs, which only flushes to a file on process exit and stayed empty once the
  // app stopped crashing). Remove once this is root-caused.
  afterTest: async (_test, _context, { passed }) => {
    if (passed) return;
    try {
      console.log("--- DIAGNOSTIC: page source at failure ---");
      console.log(await browser.getPageSource());
      const bridge = await browser.execute(() => ({
        hasTauriInternals: typeof (window as any).__TAURI_INTERNALS__ !== "undefined",
        hasTauri: typeof (window as any).__TAURI__ !== "undefined",
        readyState: document.readyState,
        bodyChildCount: document.body?.children.length ?? -1,
      }));
      console.log("--- DIAGNOSTIC: bridge/document state ---", JSON.stringify(bridge));
    } catch (e) {
      console.log("--- DIAGNOSTIC: failed to capture page state ---", e);
    }
    try {
      const logs = await browser.getLogs("browser");
      console.log("--- DIAGNOSTIC: browser console logs ---", JSON.stringify(logs, null, 2));
    } catch (e) {
      console.log("--- DIAGNOSTIC: getLogs('browser') not supported by this driver ---", e);
    }
    try {
      console.log("--- DIAGNOSTIC: document.title (index.html's error listener writes here) ---", await browser.getTitle());
    } catch (e) {
      console.log("--- DIAGNOSTIC: failed to read title ---", e);
    }
  },
};
