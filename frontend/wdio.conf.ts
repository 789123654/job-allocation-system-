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
        // Temporary — added 2026-09-15 to diagnose a CI-only startup crash (app exits code 101
        // before the embedded WebDriver server comes up; @wdio/tauri-service's own error message
        // names this option as the way to see the app's real stderr). Remove once root-caused.
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
};
