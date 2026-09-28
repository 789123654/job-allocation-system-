import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// One-time secret display, shared by create-employee-dialog.tsx and reset-password-dialog.tsx
// (code-review finding #9, 2026-09-14 — the two dialogs had hand-duplicated this block). OWASP
// MFA Cheat Sheet's OTP-handling guidance: single-use display, never logged, cleared from state
// (not just hidden) once the caller's onDone handler runs.
export function SecretRevealPanel({
  recipientLabel,
  value,
  onDone,
}: {
  recipientLabel: string;
  value: string;
  onDone: () => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-(--color-ledger-text-muted)">
        Share this temporary password with {recipientLabel} directly — it is shown only this once
        and cannot be retrieved again.
      </p>
      <Input
        readOnly
        value={value}
        onFocus={(e) => e.currentTarget.select()}
        className="font-(family-name:--font-mono)"
      />
      <Button type="button" onClick={onDone}>
        Done
      </Button>
    </div>
  );
}
