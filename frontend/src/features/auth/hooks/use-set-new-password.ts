import { useRef, useState } from "react";
import { apiRequest } from "@/lib/api-client";
import { supabase } from "@/lib/supabase-client";
import type { PasswordChangeInput } from "@/features/auth/types";

export function useSetNewPassword() {
  const [error, setError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);
  // Same synchronous guard as the sibling use-change-password.ts, ported here after a blind
  // adversarial test (code-review, 2026-09-15) found the identical bug: `isPending` state updates
  // too late to stop two rapid clicks — react-hook-form's async handleSubmit lets both reach here
  // before React commits the re-render that disables the button. ASVS 5 §15.4.2 / Business_Logic_
  // Security_Cheat_Sheet.md "Prevent Race Conditions on Sensitive Operations": check-then-act must
  // be one atomic operation; a `useRef` mutates synchronously, state doesn't. Worse here than the
  // sibling case: a double-submit fires two concurrent requests against a one-time temporary
  // credential, not just a redundant already-known password.
  const isPendingRef = useRef(false);

  async function setNewPassword(input: PasswordChangeInput): Promise<boolean> {
    if (isPendingRef.current) return false;
    isPendingRef.current = true;
    setIsPending(true);
    setError(null);
    const { error: updateError } = await supabase.auth.updateUser({
      current_password: input.currentPassword,
      password: input.newPassword,
    });
    if (updateError) {
      isPendingRef.current = false;
      setIsPending(false);
      setError(updateError.message);
      return false;
    }
    try {
      // Supabase's own updateUser() has no idea `profiles.must_change_password` exists
      // (API_SPEC.md §3) — this is the "trivial FastAPI call" that doc names as the still-needed
      // second half: it flips the DB flag so the *next* token mint (below) actually reads false.
      // Uses the still-valid pre-refresh token; CurrentProfileDep doesn't check the flag, only
      // ActiveProfileDep does, so this is allowed to run while it's still true.
      await apiRequest("/auth/confirm-password-changed", { method: "POST" });
      // must_change_password is a JWT claim (custom access token hook), only as fresh as the
      // current token — force a refresh now so session-store.tsx sees it flip to false
      // immediately, instead of waiting up to the token's remaining lifetime.
      await supabase.auth.refreshSession();
    } catch {
      // The password itself already changed on Supabase's side above — only this confirmation
      // step failed. Surface it rather than silently re-showing this screen with no explanation,
      // and unblock the guard so a retry isn't permanently locked out.
      isPendingRef.current = false;
      setIsPending(false);
      setError("Password changed, but couldn't confirm it with the server. Please try signing in again.");
      return false;
    }
    isPendingRef.current = false;
    setIsPending(false);
    return true;
  }

  return { setNewPassword, error, isPending };
}
