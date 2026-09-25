import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { env } from "@/config/env";
import { supabase } from "@/lib/supabase-client";
import { fakeSession, server } from "@/testing/mocks/handlers";
import { storeState } from "@/testing/setup-tests";

// Blind adversarial test for the security decision documented in docs/FRONTEND_ARCHITECTURE.md §6:
// the Supabase session must be persisted through the Tauri IPC-backed store (DPAPI-encrypted at
// rest on the Rust side), never through the webview's default window.localStorage. A JS test can't
// verify the DPAPI encryption itself — only that the app is actually wired to the custom adapter
// and isn't silently falling back to (or also leaking into) plain browser storage. Regression this
// guards: createClient()'s `auth.storage` option reverted to Supabase's default, or dropped in a
// merge conflict.
//
// Research (owasp-tcasvs/chapters/v3-data-storage-protection.md): 3.3.1/3.3.3 require auth
// tokens/session ids via OS-provided secure storage, not custom/plaintext storage; 3.5.3 requires
// locally-stored session state to be cleaned up on logout — that's the sign-out assertion below.
// owasp-wstg/chapters/11-client-side.md WSTG-CLNT-12 ("Test Browser Storage") is the closest
// browser-testing procedure, adapted from "enumerate localStorage/sessionStorage for tokens,
// verify cleared on logout" to this thick-client's IPC store instead of DevTools' Storage panel.
// owasp-asvs-5/chapters/v14-data-protection.md 14.3.3 (browser storage must hold no sensitive
// data except session tokens) motivates checking localStorage specifically stays empty — if this
// app were using it "correctly" per that ASVS line it would still violate the project's own
// stricter TCASVS-driven decision to keep it out of the webview entirely.

afterEach(() => {
  // These tests share the module-level `supabase` singleton and mock store across `it` blocks in
  // this file (setupFiles run once per file, not per test) — clear both so one test's leftover
  // state can't make the next test pass/fail for the wrong reason.
  storeState.clear();
  window.localStorage.clear();
});

function storedValuesContain(needle: string): boolean {
  return Array.from(storeState.values()).some((v) => JSON.stringify(v).includes(needle));
}

describe("supabase auth storage wiring", () => {
  it("persists the session into the IPC-backed store on sign-in, and not into window.localStorage", async () => {
    expect(storeState.size).toBe(0); // sanity: nothing leaked in from a prior test

    const result = await supabase.auth.signInWithPassword({
      email: "owner@example.com",
      password: "x",
    });
    if (result.error) throw result.error;

    expect(storeState.size).toBeGreaterThan(0);
    expect(storedValuesContain(fakeSession.access_token)).toBe(true);

    // The regression this whole file exists to catch: silently falling back to (or additionally
    // leaking into) the webview's default storage instead of the custom IPC adapter.
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("removes the session from the IPC-backed store on sign-out (owasp-tcasvs 3.5.3)", async () => {
    server.use(
      // supabase-js's signOut() calls this — unmocked would fail via MSW's onUnhandledRequest:
      // "error" (setup-tests.ts) rather than via a real assertion.
      http.post(`${env.SUPABASE_URL}/auth/v1/logout`, () => new HttpResponse(null, { status: 204 })),
    );

    const signInResult = await supabase.auth.signInWithPassword({
      email: "owner@example.com",
      password: "x",
    });
    if (signInResult.error) throw signInResult.error;
    expect(storedValuesContain(fakeSession.access_token)).toBe(true); // precondition

    const { error } = await supabase.auth.signOut();
    expect(error).toBeNull();

    expect(storedValuesContain(fakeSession.access_token)).toBe(false);
  });
});
