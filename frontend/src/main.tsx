import * as Sentry from "@sentry/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "@/app/app";
import { env } from "@/config/env";
import "@/index.css";

if (env.SENTRY_DSN) {
  // Must run before the first render below — same ordering requirement as backend/app/main.py's
  // sentry_sdk.init() before FastAPI(...). Frontend counterpart of that already-wired backend
  // integration (DEPLOYMENT.md §6's "Sentry, free Developer plan" decision) — the ErrorBoundary
  // added in the whole-Phase-4 code-review pass only console.error'd until now.
  //
  // Not set: sendDefaultPii (deprecated in Sentry's JS SDK in favor of `dataCollection`, both
  // still default to not collecting IP/user data) and its dataCollection replacement — left at
  // their default (no automatic PII collection), matching the backend's own deliberate
  // "send_default_pii NOT set" stance (main.py). This is a different destination and a different
  // payload shape than the backend's traces (browser errors/component stacks, not request
  // bodies/query params), so this is its own check, not an inherited assumption (skill-
  // verification-discipline.md failure mode 7) — the same "don't forward user data to a new
  // third-party destination by default" reasoning still applies here independently.
  //
  // No integrations=[...] passed — @sentry/react auto-instruments (browser tracing, etc.) from
  // Sentry.init() alone (verified against Sentry's own current React SDK docs, 2026-09-13, not
  // assumed from memory since no installed skill covers this library).
  Sentry.init({ dsn: env.SENTRY_DSN, tracesSampleRate: 1.0 });
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
