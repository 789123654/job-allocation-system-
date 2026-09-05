import type { ReactNode } from "react";
import { SessionProvider } from "@/stores/session-store";

// No QueryClientProvider yet — nothing in this slice is server-cache state (session restore is an
// onAuthStateChange subscription, not a query). Added by whichever later feature slice first needs
// TanStack Query (FRONTEND_ARCHITECTURE.md §3).
export function Provider({ children }: { children: ReactNode }) {
  return <SessionProvider>{children}</SessionProvider>;
}
