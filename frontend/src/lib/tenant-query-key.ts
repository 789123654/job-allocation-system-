// ASVS 5 §8.4.1 / Multi_Tenant_Security_Cheat_Sheet.md's "Cache & Session Isolation" section
// ("prefix all cache keys with tenant identifier" — listed bad practice: "shared cache keys
// without tenant prefixes"). Centralized here (not per-feature) so every future TanStack Query
// slice (job types, tasks, issues, notifications — CODING_STRUCTURE.md's Build Order) gets this
// by construction, instead of each feature re-deriving its own two-part key/prefix pair — found
// as a structural gap during the Employees-slice security audit (2026-09-11): the first version
// of this fix lived only in features/employees/api/get-employees.ts.
//
// firmId is null only during the brief initial session-loading render (OwnerRoute already gates
// every screen that uses this to a signed-in Owner) — the "unauthenticated" placeholder key is
// never actually fetched under, since callers pair it with `enabled: firmId !== null`
// (TanStack Query's standard "dependent query" pattern).
export function tenantQueryKey(resource: string, firmId: string | null) {
  return [resource, firmId ?? "unauthenticated"] as const;
}

// Mutation hooks invalidate this plain prefix — TanStack Query's default invalidateQueries does
// prefix/fuzzy matching (verified against tanstack.com's own invalidation guide), so this matches
// every firm-scoped key for the resource without the mutation needing to know the current firmId.
export function tenantQueryKeyPrefix(resource: string) {
  return [resource] as const;
}
