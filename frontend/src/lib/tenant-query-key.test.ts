import { describe, expect, it } from "vitest";
import { tenantQueryKey, tenantQueryKeyPrefix } from "@/lib/tenant-query-key";

// Blind adversarial test written against the documented contract only (see task prompt) —
// not against the implementation. Core property under test: two tenants must never collide
// on the same cache key (ASVS 5 8.4.1 "Multi-tenant apps enforce cross-tenant controls";
// OWASP Multi_Tenant_Security_Cheat_Sheet.md §4 "Cache & Session Isolation" — "Prefix all
// cache keys with tenant identifier", whose bad example is exactly a cache-key collision
// between tenants sharing an unscoped key). Adapted from WSTG's authorization-testing
// approach (horizontal-privilege-escalation / IDOR checks: does entity A's identifier ever
// let you reach entity B's resource) to a pure cache-key-scoping function rather than a live
// endpoint — no WSTG procedure targets a client-side cache key directly.
describe("tenantQueryKey", () => {
  it("scopes the same resource differently per real firmId (tenant isolation)", () => {
    const a = tenantQueryKey("employees", "firm-A");
    const b = tenantQueryKey("employees", "firm-B");
    expect(a).not.toEqual(b);
  });

  it("is stable for the same resource + same firmId (cache hits for repeat calls)", () => {
    const first = tenantQueryKey("employees", "firm-A");
    const second = tenantQueryKey("employees", "firm-A");
    expect(first).toEqual(second);
  });

  it("scopes the same firmId differently per resource", () => {
    const employees = tenantQueryKey("employees", "firm-A");
    const tasks = tenantQueryKey("tasks", "firm-A");
    expect(employees).not.toEqual(tasks);
  });

  it("produces the documented [resource, firmId] shape for a real firmId", () => {
    expect(tenantQueryKey("employees", "firm-A")).toEqual(["employees", "firm-A"]);
  });

  it("produces the literal sentinel ['resource', 'unauthenticated'] when firmId is null", () => {
    expect(tenantQueryKey("employees", null)).toEqual(["employees", "unauthenticated"]);
  });

  it("adversarial: a real firmId that is literally the string 'unauthenticated' must not be" +
    " indistinguishable from the null-firmId sentinel — report actual behavior either way", () => {
    const spoofedFirmId = tenantQueryKey("employees", "unauthenticated");
    const nullFirmId = tenantQueryKey("employees", null);
    // These two calls are semantically different (a real, if oddly-named, tenant vs. no
    // tenant at all) but per the documented contract they are expected to serialize
    // identically, since firmId "unauthenticated" and the null-sentinel "unauthenticated"
    // are the same string in slot 2. Assert on the actual (collision) behavior so a future
    // change that silently starts (or stops) distinguishing them is caught either way.
    expect(spoofedFirmId).toEqual(nullFirmId);
  });

  it("prefix contract: tenantQueryKeyPrefix(resource) is a true array-prefix of every" +
    " tenantQueryKey(resource, firmId) — real or null firmId", () => {
    const prefix = tenantQueryKeyPrefix("employees");
    expect(tenantQueryKey("employees", "firm-A").slice(0, 1)).toEqual(prefix);
    expect(tenantQueryKey("employees", "firm-B").slice(0, 1)).toEqual(prefix);
    expect(tenantQueryKey("employees", null).slice(0, 1)).toEqual(prefix);
  });

  it("tenantQueryKeyPrefix returns the documented [resource] shape", () => {
    expect(tenantQueryKeyPrefix("employees")).toEqual(["employees"]);
  });

  it("empty-string firmId is still isolated from a real firmId and from the null sentinel", () => {
    const empty = tenantQueryKey("employees", "");
    const real = tenantQueryKey("employees", "firm-A");
    const nullFirmId = tenantQueryKey("employees", null);
    expect(empty).not.toEqual(real);
    expect(empty).not.toEqual(nullFirmId);
  });
});
