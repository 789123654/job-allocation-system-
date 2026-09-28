import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { env } from "@/config/env";
import { apiRequest, ApiError } from "@/lib/api-client";
import { supabase } from "@/lib/supabase-client";
import { fakeSession, server } from "@/testing/mocks/handlers";

describe("apiRequest", () => {
  beforeEach(async () => {
    // Populate an in-memory session so authHeaders() has a real access_token to attach —
    // signInWithPassword hits MSW's fake token endpoint (testing/mocks/handlers.ts).
    const result = await supabase.auth.signInWithPassword({
      email: "owner@example.com",
      password: "x",
    });
    if (result.error) throw result.error;
  });

  it("attaches the Authorization header from the current session", async () => {
    let capturedAuth: string | null = null;
    server.use(
      http.get(`${env.API_BASE_URL}/ping`, ({ request }) => {
        capturedAuth = request.headers.get("Authorization");
        return HttpResponse.json({ ok: true });
      }),
    );

    await apiRequest("/ping");

    expect(capturedAuth).toBe(`Bearer ${fakeSession.access_token}`);
  });

  it("attaches the Idempotency-Key exactly as given, only when one is passed", async () => {
    let capturedKey: string | null = null;
    server.use(
      http.post(`${env.API_BASE_URL}/tasks`, ({ request }) => {
        capturedKey = request.headers.get("Idempotency-Key");
        return HttpResponse.json({ ok: true }, { status: 201 });
      }),
    );

    await apiRequest("/tasks", {
      method: "POST",
      body: { title: "x" },
      idempotencyKey: "caller-owned-key-1",
    });

    expect(capturedKey).toBe("caller-owned-key-1");
  });

  it("reuses the exact same key across two calls when the caller passes the same one — rest-api-guidelines Rule 230: this is what lets a retry of one logical operation dedupe server-side, instead of looking like a brand-new request", async () => {
    const capturedKeys: Array<string | null> = [];
    server.use(
      http.post(`${env.API_BASE_URL}/tasks`, ({ request }) => {
        capturedKeys.push(request.headers.get("Idempotency-Key"));
        return HttpResponse.json({ ok: true }, { status: 201 });
      }),
    );

    const key = "retry-of-one-logical-operation";
    await apiRequest("/tasks", { method: "POST", body: { title: "x" }, idempotencyKey: key });
    await apiRequest("/tasks", { method: "POST", body: { title: "x" }, idempotencyKey: key });

    expect(capturedKeys).toEqual([key, key]);
  });

  it("sends no Idempotency-Key header when none is passed", async () => {
    let capturedKey: string | null = "unset";
    server.use(
      http.get(`${env.API_BASE_URL}/ping`, ({ request }) => {
        capturedKey = request.headers.get("Idempotency-Key");
        return HttpResponse.json({ ok: true });
      }),
    );

    await apiRequest("/ping");

    expect(capturedKey).toBeNull();
  });

  it("signs the client out on a 401 (code-review finding #19) — ordinary regression test, not blind: the server-side boundary (api/deps.py's get_current_profile) is what actually rejects a deactivated/deleted-firm token; this only verifies the client follows that rejection instead of sitting on a dead session, per owasp-wstg's Session Management chapter (WSTG-SESS-06, adapted — no WSTG procedure targets a mid-session server-issued rejection directly, the closest named one is logout termination actually propagating)", async () => {
    server.use(
      http.get(`${env.API_BASE_URL}/ping`, () =>
        HttpResponse.json(
          {
            type: "about:blank",
            title: "Unauthorized",
            status: 401,
            detail: "Account inactive or not found",
            instance: "",
          },
          { status: 401 },
        ),
      ),
      // supabase-js's signOut() call — unmocked, MSW's onUnhandledRequest: "error" (setup-tests.ts)
      // would otherwise fail the test on this request rather than on a real assertion.
      http.post(`${env.SUPABASE_URL}/auth/v1/logout`, () => new HttpResponse(null, { status: 204 })),
    );

    await expect(apiRequest("/ping")).rejects.toBeInstanceOf(ApiError);

    // signOut() is fire-and-forget inside apiRequest (doesn't block the throw above) — wait for
    // the session to actually clear rather than asserting immediately after the await above.
    await expect
      .poll(async () => (await supabase.auth.getSession()).data.session)
      .toBeNull();
  });
});
