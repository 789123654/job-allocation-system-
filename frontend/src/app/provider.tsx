import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { queryClient } from "@/lib/query-client";
import { SessionProvider } from "@/stores/session-store";

// QueryClientProvider added here (FRONTEND_ARCHITECTURE.md §3) — the employees feature slice is
// the first with server-cache-state data (task/job-type/issue/notification slices reuse this same
// provider, nothing further to add here when they land).
export function Provider({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider>{children}</SessionProvider>
    </QueryClientProvider>
  );
}
