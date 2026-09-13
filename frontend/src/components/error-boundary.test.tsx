import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ErrorBoundary } from "@/components/error-boundary";

/**
 * Security verification (OWASP Logging & Error Handling):
 * - OWASP Error_Handling_Cheat_Sheet: Errors logged server-side, generic responses to user; no stack traces/secrets to client.
 * - OWASP Logging_Cheat_Sheet: Logged data is a high-value asset; treat untrusted data carefully; PII logging requires data protection level compliance (V16.2.5 ASVS).
 * - OWASP ASVS V16.5.1: Security-sensitive errors return generic message, no exposure of implementation details.
 * - OWASP ASVS V16.5.4: Unhandled exceptions caught by last-resort handler; details preserved for logs.
 * - CRITICAL: Tauri desktop app (non-server) should not exfiltrate error data to third-party services without explicit user consent via DSN configuration.
 *   This test specifically verifies the privacy guard: when SENTRY_DSN is falsy, Sentry must never be called to prevent unintended data exfiltration.
 */

// Mock Sentry and env modules
const mocks = vi.hoisted(() => ({
  captureReactException: vi.fn(),
  env: { SENTRY_DSN: undefined as string | undefined },
}));

vi.mock("@sentry/react", () => ({
  captureReactException: mocks.captureReactException,
}));

vi.mock("@/config/env", () => ({
  env: mocks.env,
}));

// Throwing component for testing error boundary
function Bomb(): never {
  throw new Error("boom");
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    mocks.captureReactException.mockClear();
    mocks.env.SENTRY_DSN = undefined;
  });

  it("renders children normally when no error occurs", () => {
    render(
      <ErrorBoundary fallbackMessage="Something went wrong">
        <div>Hello, World!</div>
      </ErrorBoundary>
    );

    expect(screen.getByText("Hello, World!")).toBeDefined();
  });

  it("catches a thrown error and renders the fallback message instead of crashing", () => {
    // Suppress React's own console.error for this test to keep output clean
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ErrorBoundary fallbackMessage="Application encountered an error">
        <Bomb />
      </ErrorBoundary>
    );

    expect(
      screen.getByText("Application encountered an error")
    ).toBeDefined();
    consoleErrorSpy.mockRestore();
  });

  it("calls console.error when an error is caught", () => {
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ErrorBoundary fallbackMessage="Error occurred">
        <Bomb />
      </ErrorBoundary>
    );

    // ErrorBoundary itself calls console.error("ErrorBoundary caught:", error, info) — the error
    // object is the 2nd argument, not the 1st (React also makes its own internal console.error
    // calls during this render, which is why we check "some call" rather than the spy's first
    // call specifically).
    expect(consoleErrorSpy.mock.calls.some((call) => call[1] instanceof Error && call[1].message === "boom")).toBe(true);
    consoleErrorSpy.mockRestore();
  });

  it("calls Sentry.captureReactException when SENTRY_DSN is a truthy string", () => {
    mocks.env.SENTRY_DSN = "https://key@sentry.io/project";
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ErrorBoundary fallbackMessage="Error occurred">
        <Bomb />
      </ErrorBoundary>
    );

    expect(mocks.captureReactException).toHaveBeenCalledTimes(1);
    expect(mocks.captureReactException).toHaveBeenCalledWith(
      expect.objectContaining({ message: "boom" }),
      expect.any(Object) // ErrorInfo object
    );
    consoleErrorSpy.mockRestore();
  });

  it("does NOT call Sentry.captureReactException when SENTRY_DSN is undefined", () => {
    mocks.env.SENTRY_DSN = undefined;
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ErrorBoundary fallbackMessage="Error occurred">
        <Bomb />
      </ErrorBoundary>
    );

    expect(mocks.captureReactException).not.toHaveBeenCalled();
    consoleErrorSpy.mockRestore();
  });

  it("does NOT call Sentry.captureReactException when SENTRY_DSN is an empty string", () => {
    mocks.env.SENTRY_DSN = "";
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ErrorBoundary fallbackMessage="Error occurred">
        <Bomb />
      </ErrorBoundary>
    );

    expect(mocks.captureReactException).not.toHaveBeenCalled();
    consoleErrorSpy.mockRestore();
  });

  it("does NOT call any Sentry function when SENTRY_DSN is falsy, preventing data exfiltration", () => {
    // This is the critical test: verify that no Sentry exports are called
    // when DSN is not configured, protecting privacy in a Tauri desktop app.
    mocks.env.SENTRY_DSN = undefined;
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ErrorBoundary fallbackMessage="Error occurred">
        <Bomb />
      </ErrorBoundary>
    );

    // Verify the gate works: no Sentry function called
    expect(mocks.captureReactException).not.toHaveBeenCalled();

    consoleErrorSpy.mockRestore();
  });

  it("passes the correct error and ErrorInfo objects to Sentry", () => {
    mocks.env.SENTRY_DSN = "https://key@sentry.io/project";
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ErrorBoundary fallbackMessage="Error occurred">
        <Bomb />
      </ErrorBoundary>
    );

    const callArgs = mocks.captureReactException.mock.calls[0];
    const error = callArgs[0];
    const errorInfo = callArgs[1];

    // Verify error object
    expect(error).toBeInstanceOf(Error);
    expect(error.message).toBe("boom");

    // Verify ErrorInfo object (React's error info contains componentStack)
    expect(errorInfo).toHaveProperty("componentStack");

    consoleErrorSpy.mockRestore();
  });
});
