import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { env } from "@/config/env";
import { apiRequest } from "@/lib/api-client";
import { supabase } from "@/lib/supabase-client";
import { server } from "@/testing/mocks/handlers";

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

    expect(capturedAuth).toBe("Bearer fake-access-token");
  });

  it("attaches a fresh Idempotency-Key only when requested", async () => {
    let capturedKey: string | null = null;
    server.use(
      http.post(`${env.API_BASE_URL}/tasks`, ({ request }) => {
        capturedKey = request.headers.get("Idempotency-Key");
        return HttpResponse.json({ ok: true }, { status: 201 });
      }),
    );

    await apiRequest("/tasks", { method: "POST", body: { title: "x" }, idempotent: true });

    // crypto.randomUUID() format — asserting shape, not a specific value.
    expect(capturedKey).toMatch(/^[0-9a-f-]{36}$/);
  });
});
