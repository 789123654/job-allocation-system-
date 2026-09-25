import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import {
  isAlreadyResetConflict,
  useResetEmployeePassword,
} from "@/features/employees/api/reset-employee-password";
import { SecretRevealPanel } from "@/features/employees/components/secret-reveal-panel";

export function ResetPasswordDialog({
  employeeId,
  employeeName,
  open,
  onOpenChange,
}: {
  employeeId: string;
  employeeName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  // Generated once per dialog-open attempt (rest-api-guidelines Rule 230, api-client.ts's fix) —
  // reused across any retry within this attempt; closing and reopening starts a new attempt with
  // a fresh key, which is the correct boundary (a deliberate second reset, not a network retry).
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());
  // OWASP MFA Cheat Sheet's OTP-handling guidance: single-use display, cleared on close.
  const [generatedPassword, setGeneratedPassword] = useState<string | null>(null);
  const resetPassword = useResetEmployeePassword();

  function handleOpenChange(next: boolean) {
    onOpenChange(next);
    if (!next) {
      setGeneratedPassword(null);
      resetPassword.reset();
      setIdempotencyKey(crypto.randomUUID());
    }
  }

  async function handleConfirm() {
    try {
      const password = await resetPassword.mutateAsync({ employeeId, idempotencyKey });
      setGeneratedPassword(password);
    } catch {
      // resetPassword.isError/.error rendered below.
    }
  }

  const errorMessage = resetPassword.isError
    ? isAlreadyResetConflict(resetPassword.error)
      ? "Already reset — check with the employee before resetting again"
      : "Something went wrong — try again"
    : null;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogTitle>Reset password for {employeeName}</DialogTitle>
        {generatedPassword ? (
          <SecretRevealPanel
            recipientLabel={employeeName}
            value={generatedPassword}
            onDone={() => handleOpenChange(false)}
          />
        ) : (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-(--color-ledger-text-muted)">
              This immediately invalidates {employeeName}&rsquo;s current password and forces them
              to set a new one on next login.
            </p>
            {errorMessage && (
              <p className="text-sm text-(--color-ledger-danger)">{errorMessage}</p>
            )}
            <Button type="button" onClick={handleConfirm} disabled={resetPassword.isPending}>
              {resetPassword.isPending ? "Resetting…" : "Reset password"}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
