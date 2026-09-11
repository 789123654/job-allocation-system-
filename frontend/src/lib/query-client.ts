import { QueryClient } from "@tanstack/react-query";

// FRONTEND_ARCHITECTURE.md §3/§4: one preconfigured, reused-everywhere instance — same
// single-client pattern as lib/api-client.ts. No custom retry/staleTime overrides: TanStack
// Query's defaults (3 retries for queries, 0 for mutations — verified against tanstack.com's own
// docs, not assumed) are the right shape here; mutations must not silently auto-retry a
// non-idempotent-by-default call.
export const queryClient = new QueryClient();
