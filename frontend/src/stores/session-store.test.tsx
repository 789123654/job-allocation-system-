import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { queryClient } from "@/lib/query-client";
import { SessionProvider } from "@/stores/session-store";

let capturedCallback: ((event: string, session: unknown) => void) | null = null;

vi.mock("@/lib/supabase-client", () => ({
  supabase: {
    auth: {
      getSession: () => Promise.resolve({ data: { session: null } }),
      onAuthStateChange: (cb: (event: string, session: unknown) => void) => {
        capturedCallback = cb;
        return { data: { subscription: { unsubscribe: () => undefined } } };
      },
    },
  },
}));

describe("SessionProvider", () => {
  // ASVS 5 §14.3.1 — authenticated data cleared from client storage on session termination.
  // Directly exercises the onAuthStateChange callback's own cache-clearing branch (not the
  // initial mount's getSession() resolution, which is a different code path) — a shared device
  // where a second user signs in afterward must never see the first user's cached data.
  it("clears the shared query cache when the session transitions to null", () => {
    queryClient.setQueryData(["employees", "some-firm"], [{ id: "e1" }]);
    expect(queryClient.getQueryData(["employees", "some-firm"])).toBeDefined();

    render(
      <QueryClientProvider client={queryClient}>
        <SessionProvider>{null}</SessionProvider>
      </QueryClientProvider>,
    );

    expect(capturedCallback).not.toBeNull();
    capturedCallback?.("SIGNED_OUT", null);

    expect(queryClient.getQueryData(["employees", "some-firm"])).toBeUndefined();
  });
});
