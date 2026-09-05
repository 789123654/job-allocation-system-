import { useState } from "react";
import { supabase } from "@/lib/supabase-client";
import type { PasswordChangeInput } from "@/features/auth/types";

export function useSetNewPassword() {
  const [error, setError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);

  async function setNewPassword(input: PasswordChangeInput): Promise<boolean> {
    setIsPending(true);
    setError(null);
    const { error: updateError } = await supabase.auth.updateUser({
      current_password: input.currentPassword,
      password: input.newPassword,
    });
    if (updateError) {
      setIsPending(false);
      setError(updateError.message);
      return false;
    }
    // must_change_password is a JWT claim (custom access token hook), only as fresh as the
    // current token — force a refresh now so session-store.tsx sees it flip to false
    // immediately, instead of waiting up to the token's remaining lifetime.
    await supabase.auth.refreshSession();
    setIsPending(false);
    return true;
  }

  return { setNewPassword, error, isPending };
}
