import * as Sentry from "@sentry/react";
import { Component, type ErrorInfo, type ReactNode } from "react";
import { env } from "@/config/env";

// Plain React error boundary (react.dev's own componentDidCatch/getDerivedStateFromError pattern
// — only a class component can catch render errors, no hook equivalent exists). No third-party
// dependency added for this: CODING_STRUCTURE.md's error-handling section (bulletproof-react/docs/
// error-handling.md) calls for "multiple error boundaries, scoped per section, not one global
// boundary," which this project had zero of anywhere (code-review finding, whole-Phase-4 sweep,
// 2026-09-13) — this is the shared, reusable boundary each scoped section wraps itself in.
interface Props {
  children: ReactNode;
  fallbackMessage: string;
}

interface State {
  hasError: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("ErrorBoundary caught:", error, info);
    // Explicitly guarded, same as deps.py's sentry_sdk.set_tag call on the backend — Sentry's own
    // docs don't state whether SDK functions are safe to call before init() (checked directly,
    // 2026-09-13, not assumed either way), so this doesn't rely on that being true. main.tsx only
    // calls Sentry.init() when VITE_SENTRY_DSN is set; this mirrors that same condition rather
    // than trusting an unverified implicit no-op.
    //
    // captureReactException (not a plain captureException) is the SDK's own current, dedicated API
    // for this exact call site — it parses `info.componentStack` and attaches it via `error.cause`
    // automatically (verified against Sentry's current React SDK docs, 2026-09-13; requires SDK
    // >=9.8.0, this project installs ^10.74.0).
    if (env.SENTRY_DSN) {
      Sentry.captureReactException(error, info);
    }
  }

  render() {
    if (this.state.hasError) {
      return <p className="text-sm text-(--color-ledger-danger)">{this.props.fallbackMessage}</p>;
    }
    return this.props.children;
  }
}
