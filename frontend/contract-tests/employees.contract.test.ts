// Runs against the REAL FastAPI backend + the real local Supabase stack (CI's `e2e` job only —
// see vitest.contract.config.ts and .github/workflows/ci.yml), not MSW. The whole point: the
// employees-slice unit tests (employee-management-page.test.tsx) only prove the frontend's
// fetchers agree with a mock WE wrote — they can't catch us getting the same field wrong in both
// the fetcher and the mock. This imports the actual shipped mapper functions (toEmployee,
// toEmployeeCreated) and feeds them real backend responses, so a real drift between what
// employees.py returns and what the frontend assumes fails here.
import { describe, expect, it } from "vitest";
import {
  toEmployee,
  toEmployeeCreated,
  type EmployeeCreatedDto,
  type EmployeeOutDto,
} from "@/features/employees/api/mappers";

const BASE_URL = process.env.CONTRACT_API_BASE_URL;
const TOKEN = process.env.CONTRACT_TEST_TOKEN;

// Skipped everywhere except the e2e job, same gating shape as backend/tests/e2e's E2E=1 check.
const describeIfConfigured = BASE_URL && TOKEN ? describe : describe.skip;

async function call(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${TOKEN}`,
      "Content-Type": "application/json",
      ...init.headers,
    },
  });
}

describeIfConfigured("employees API contract (real backend, not MSW)", () => {
  it("create -> list -> deactivate -> reset-password all parse through the app's real mappers", async () => {
    const email = `contract-${crypto.randomUUID()}@example.com`;

    const createRes = await call("/employees", {
      method: "POST",
      body: JSON.stringify({ full_name: "Contract Test", email }),
    });
    expect(createRes.status).toBe(201);
    const created = toEmployeeCreated((await createRes.json()) as EmployeeCreatedDto);
    expect(created.fullName).toBe("Contract Test");
    expect(created.email).toBe(email);
    expect(created.generatedPassword.length).toBeGreaterThan(0);
    expect(created.isActive).toBe(true);

    const listRes = await call("/employees");
    expect(listRes.status).toBe(200);
    const listed = ((await listRes.json()) as EmployeeOutDto[]).map(toEmployee);
    expect(listed.find((e) => e.email === email)).toEqual({
      id: created.id,
      fullName: "Contract Test",
      email,
      isActive: true,
    });

    const patchRes = await call(`/employees/${created.id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_active: false }),
    });
    expect(patchRes.status).toBe(200);
    const patched = toEmployee((await patchRes.json()) as EmployeeOutDto);
    expect(patched.isActive).toBe(false);

    // Real Idempotency-Key round trip against the real endpoint the api-client.ts fix was for.
    const key = crypto.randomUUID();
    const resetRes = await call(`/employees/${created.id}/reset-password`, {
      method: "POST",
      headers: { "Idempotency-Key": key },
    });
    expect(resetRes.status).toBe(200);
    const reset = (await resetRes.json()) as { generated_password: string };
    expect(reset.generated_password.length).toBeGreaterThan(0);

    // A genuine retry with the SAME key must dedupe (409), not silently succeed twice — this is
    // the exact server-side behavior the client-owned-key fix (lib/api-client.ts) depends on.
    const retryRes = await call(`/employees/${created.id}/reset-password`, {
      method: "POST",
      headers: { "Idempotency-Key": key },
    });
    expect(retryRes.status).toBe(409);
  });

  it("a duplicate email returns the exact problem+json shape ApiError.problem reads", async () => {
    const email = `contract-dup-${crypto.randomUUID()}@example.com`;
    await call("/employees", { method: "POST", body: JSON.stringify({ full_name: "A", email }) });

    const res = await call("/employees", {
      method: "POST",
      body: JSON.stringify({ full_name: "B", email }),
    });

    expect(res.status).toBe(409);
    const problem = (await res.json()) as { detail: string };
    expect(problem.detail).toBe("Email already in use");
  });
});
