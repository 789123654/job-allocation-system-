import { useState } from "react";
import { supabase } from "@/lib/supabase-client";
import type { PasswordChangeInput } from "@/features/auth/types";

export function useChangePassword() {
  const [error, setError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);

  async function changePassword(input: PasswordChangeInput): Promise<boolean> {
    setIsPending(true);
    setError(null);
    // ARCHITECTURE.md §4 / supabase/auth/password-security.md: current_password required so a
    // change can't be forced through a stolen/still-open session alone.
    const { error: updateError } = await supabase.auth.updateUser({
      current_password: input.currentPassword,
      password: input.newPassword,
    });
    setIsPending(false);
    if (updateError) {
      setError(updateError.message);
      return false;
    }
    return true;
  }

  return { changePassword, error, isPending };
}
