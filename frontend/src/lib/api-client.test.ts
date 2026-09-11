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
});
