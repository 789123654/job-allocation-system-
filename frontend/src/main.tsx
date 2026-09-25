import * as Sentry from "@sentry/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "@/app/app";
import { env } from "@/config/env";
import { buildSentryOptions } from "@/lib/sentry-context";
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
  //
  // 2026-09-19: options now come from buildSentryOptions (lib/sentry-context.ts) so they're unit
  // tested: release + environment tags, the tenant tag (only the opaque firm UUID), and breadcrumb
  // scrubbing — Sentry's default click breadcrumbs would otherwise carry title/aria-label values,
  // e.g. a task description, to a third party (TCASVS 3.2.3).
  Sentry.init(
    buildSentryOptions({
      dsn: env.SENTRY_DSN,
      release: env.SENTRY_RELEASE,
      environment: import.meta.env.MODE,
    }),
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
