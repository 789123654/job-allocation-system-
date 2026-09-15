import { useRef, useState } from "react";
import { supabase } from "@/lib/supabase-client";
import type { PasswordChangeInput } from "@/features/auth/types";

export function useChangePassword() {
  const [error, setError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);
  // A synchronous guard, not just `isPending` state — found by a blind adversarial test
  // (code-review, 2026-09-15): react-hook-form's handleSubmit is async even for a synchronous
  // zodResolver, so two rapid submit clicks both reach here before React commits the re-render
  // that would disable the submit button on `isPending`, firing two concurrent password-change
  // requests. ASVS 5 §15.4.2 / Business_Logic_Security_Cheat_Sheet.md "Prevent Race Conditions on
  // Sensitive Operations": a check-then-act must be one atomic operation. No prior instance of
  // this exact bug class exists elsewhere in this codebase to reuse a fix from (grepped
  // CODE_REVIEW_FINDINGS_2026-09-14.md and every `useRef` call site — this is the first). A
  // `useRef` mutates synchronously (unlike state), so checking-and-setting it in the same call is
  // the actual atomic guard React state alone can't provide here.
  const isPendingRef = useRef(false);

  async function changePassword(input: PasswordChangeInput): Promise<boolean> {
    if (isPendingRef.current) return false;
    isPendingRef.current = true;
    setIsPending(true);
    setError(null);
    // ARCHITECTURE.md §4 / supabase/auth/password-security.md: current_password required so a
    // change can't be forced through a stolen/still-open session alone.
    const { error: updateError } = await supabase.auth.updateUser({
      current_password: input.currentPassword,
      password: input.newPassword,
    });
    isPendingRef.current = false;
    setIsPending(false);
    if (updateError) {
      setError(updateError.message);
      return false;
    }
    return true;
  }

  return { changePassword, error, isPending };
}
