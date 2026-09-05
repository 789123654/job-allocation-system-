import { useState } from "react";
import { supabase } from "@/lib/supabase-client";
import type { LoginInput } from "@/features/auth/types";

export function useLogin() {
  const [error, setError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);

  async function login(input: LoginInput): Promise<boolean> {
    setIsPending(true);
    setError(null);
    const { error: signInError } = await supabase.auth.signInWithPassword(input);
    setIsPending(false);
    if (signInError) {
      // Never relay Supabase's own error text verbatim as a matter of course elsewhere in this
      // project (API_SPEC.md §1 Rule 177) — invalid-credentials is the one message safe to show
      // as-is, since it deliberately doesn't distinguish "wrong email" from "wrong password".
      setError("Invalid email or password");
      return false;
    }
    return true;
  }

  return { login, error, isPending };
}
