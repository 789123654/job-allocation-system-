import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "@/lib/supabase-client";

// Lives here (shared), not in features/auth/ — the ESLint unidirectional-import rule forbids one
// feature importing another, and later feature slices (Employees, Tasks, ...) need this for
// RBAC-UI-display (FRONTEND_ARCHITECTURE.md §6) without reaching into features/auth/ directly.
interface SessionState {
  session: Session | null;
  role: "owner" | "employee" | null;
  mustChangePassword: boolean;
  isLoading: boolean;
}

const SessionContext = createContext<SessionState | undefined>(undefined);

function deriveState(session: Session | null, isLoading: boolean): SessionState {
  const appMetadata = session?.user.app_metadata as
    { role?: "owner" | "employee"; must_change_password?: boolean } | undefined;
  return {
    session,
    role: appMetadata?.role ?? null,
    // Decoded from the JWT for UX routing only, per ARCHITECTURE.md §4/FRONTEND_ARCHITECTURE.md
    // §6 — the real gate is backend/app/api/deps.py's require_password_set on every request.
    mustChangePassword: appMetadata?.must_change_password ?? false,
    isLoading,
  };
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>(() => deriveState(null, true));

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setState(deriveState(data.session, false));
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setState(deriveState(session, false));
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
