import { Component, type ErrorInfo, type ReactNode } from "react";

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
    // No error-tracking service wired up yet (CODING_STRUCTURE.md §4's Sentry decision is still
    // pending implementation) — this is the only surface until then.
    console.error("ErrorBoundary caught:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return <p className="text-sm text-(--color-ledger-danger)">{this.props.fallbackMessage}</p>;
    }
    return this.props.children;
  }
}
