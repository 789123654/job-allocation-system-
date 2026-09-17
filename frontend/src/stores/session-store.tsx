import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { Session } from "@supabase/supabase-js";
import { queryClient } from "@/lib/query-client";
import { supabase } from "@/lib/supabase-client";

// Lives here (shared), not in features/auth/ — the ESLint unidirectional-import rule forbids one
// feature importing another, and later feature slices (Employees, Tasks, ...) need this for
// RBAC-UI-display (FRONTEND_ARCHITECTURE.md §6) without reaching into features/auth/ directly.
interface SessionState {
  session: Session | null;
  role: "owner" | "employee" | null;
  firmId: string | null;
  mustChangePassword: boolean;
  isLoading: boolean;
}

const SessionContext = createContext<SessionState | undefined>(undefined);

type JwtAppMetadata = { role?: "owner" | "employee"; firm_id?: string; must_change_password?: boolean };

function deriveState(
  session: Session | null,
  appMetadata: JwtAppMetadata | undefined,
  isLoading: boolean,
): SessionState {
  return {
    session,
    role: appMetadata?.role ?? null,
    // ASVS 5 §8.4.1 / Multi_Tenant_Security_Cheat_Sheet.md ("prefix all cache keys with tenant
    // identifier") — feature slices' TanStack Query keys must include this, not just "employees".
    firmId: appMetadata?.firm_id ?? null,
    // Decoded from the JWT for UX routing only, per ARCHITECTURE.md §4/FRONTEND_ARCHITECTURE.md
    // §6 — the real gate is backend/app/api/deps.py's require_password_set on every request.
    mustChangePassword: appMetadata?.must_change_password ?? false,
    isLoading,
  };
}

// ASVS 5 §14.3.1 — authenticated data cleared from client storage after session termination.
// TanStack Query's cache is in-memory, not localStorage, but it's the same property: it outlives
// the route-level redirect-to-/login (that only unmounts the component tree), and on a shared
// device a different user logging in afterward would otherwise see the previous session's cached
// data (e.g. the employee list) until their own first refetch overwrites it.
//
// One shared function for BOTH the initial getSession() resolution and every later
// onAuthStateChange transition — found during the Employees-slice security audit (2026-09-11,
// code-review pass) that having the clear-on-null check only in the onAuthStateChange branch was
// itself a gap: `queryClient` is a module-level singleton that outlives any one SessionProvider
// mount, so a remount (StrictMode's dev double-invoke, or a future routing change) whose initial
// getSession() resolves null would have left a prior mount's cached data sitting there uncleared.
//
// Deliberately redundant with lib/tenant-query-key.ts's firmId-scoped keys, not competing with
// it: the scoped key is the preventive control (a different firm's key never collides with this
// one, even if some cache entry somehow survived); this clear() is the reactive one (nothing
// survives a session boundary at all, regardless of whose key it was under). Both are cheap; only
// relying on one and calling the other "redundant" would reopen exactly the gap this pass found.
async function applySessionUpdate(
  setState: (state: SessionState) => void,
  session: Session | null,
  isLoading: boolean,
): Promise<void> {
  if (!session) {
    setState(deriveState(null, undefined, isLoading));
    queryClient.clear();
    return;
  }
  // session.user.app_metadata reflects auth.users' own stored row only — the installed SDK's own
  // docs (GoTrueClient.js getSession()) say outright this "must not be trusted" for authorization
  // decisions; use getClaims() instead. The Custom Access Token Hook (a8e6def15927) only ever
  // modifies the JWT's own claims, never the stored user row, so must_change_password — which the
  // hook adds and nothing else ever sets — was silently always undefined via the old path. Found
  // 2026-09-16 testing against the real Supabase project: every login skipped the forced
  // Set New Password screen outright, confirmed against decoded JWT claims that the hook was
  // working correctly all along — only this file was reading the wrong source.
  const { data, error } = await supabase.auth.getClaims();
  if (error || !data) {
    setState(deriveState(session, undefined, isLoading));
    return;
  }
  const appMetadata = data.claims.app_metadata as JwtAppMetadata | undefined;
  setState(deriveState(session, appMetadata, isLoading));
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>(() => deriveState(null, undefined, true));

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      void applySessionUpdate(setState, data.session, false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      void applySessionUpdate(setState, session, false);
    });

    return () => subscription.unsubscribe();
  }, []);

  return <SessionContext.Provider value={state}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionState {
  const context = useContext(SessionContext);
  if (context === undefined) {
    throw new Error("useSession must be used within a SessionProvider");
  }
  return context;
}
