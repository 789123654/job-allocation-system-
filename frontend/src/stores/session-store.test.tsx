import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { queryClient } from "@/lib/query-client";
import { SessionProvider, useSession } from "@/stores/session-store";

let capturedCallback: ((event: string, session: unknown) => void) | null = null;
let getClaimsResult: unknown = { data: null, error: { message: "no session" } };

vi.mock("@/lib/supabase-client", () => ({
  supabase: {
    auth: {
      getSession: () => Promise.resolve({ data: { session: null } }),
      onAuthStateChange: (cb: (event: string, session: unknown) => void) => {
        capturedCallback = cb;
        return { data: { subscription: { unsubscribe: () => undefined } } };
      },
      getClaims: () => Promise.resolve(getClaimsResult),
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

  // Regression test for the 2026-09-16 bug: deriveState previously read must_change_password from
  // session.user.app_metadata — a field the Custom Access Token Hook never touches (it only
  // modifies the JWT's own claims). That silently defaulted mustChangePassword to false for every
  // login. Deliberately gives session.user.app_metadata the OPPOSITE values of getClaims()'s
  // claims.app_metadata below, so this test fails if the fix ever regresses back to reading the
  // untrusted user object.
  it("derives role/firmId/mustChangePassword from getClaims(), not session.user.app_metadata", async () => {
    getClaimsResult = {
      data: {
        claims: {
          app_metadata: { role: "owner", firm_id: "real-firm-id", must_change_password: true },
        },
      },
      error: null,
    };
    const fakeSession = {
      user: {
        app_metadata: { role: "employee", firm_id: "wrong-firm-id", must_change_password: false },
      },
    };

    function Probe() {
      const { role, firmId, mustChangePassword } = useSession();
      return (
        <span data-testid="probe">
          {role}|{firmId}|{String(mustChangePassword)}
        </span>
      );
    }

    render(
      <QueryClientProvider client={queryClient}>
        <SessionProvider>
          <Probe />
        </SessionProvider>
      </QueryClientProvider>,
    );

    capturedCallback?.("SIGNED_IN", fakeSession);

    await waitFor(() => {
      expect(screen.getByTestId("probe")).toHaveTextContent("owner|real-firm-id|true");
    });
  });
});
