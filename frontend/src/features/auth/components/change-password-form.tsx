import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useChangePassword } from "@/features/auth/hooks/use-change-password";
import { passwordChangeSchema, type PasswordChangeInput } from "@/features/auth/types";

export function ChangePasswordForm({ onSuccess }: { onSuccess?: () => void }) {
  const { changePassword, error, isPending } = useChangePassword();
  const [succeeded, setSucceeded] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<PasswordChangeInput>({ resolver: zodResolver(passwordChangeSchema) });

  async function onSubmit(input: PasswordChangeInput) {
    const success = await changePassword(input);
    if (success) {
      setSucceeded(true);
      onSuccess?.();
    }
  }

  if (succeeded) {
    return <p className="text-sm text-(--color-ledger-text)">Password changed successfully.</p>;
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex w-full flex-col gap-4">
      <div>
        <Label htmlFor="currentPassword">Current password</Label>
        <Input
          id="currentPassword"
          type="password"
          autoComplete="current-password"
          {...register("currentPassword")}
        />
        {errors.currentPassword && (
          <p className="mt-1 text-sm text-(--color-ledger-danger)">
            {errors.currentPassword.message}
          </p>
        )}
      </div>
      <div>
        <Label htmlFor="newPassword">New password</Label>
        <Input
          id="newPassword"
          type="password"
          autoComplete="new-password"
          {...register("newPassword")}
        />
        {errors.newPassword && (
          <p className="mt-1 text-sm text-(--color-ledger-danger)">{errors.newPassword.message}</p>
        )}
      </div>
      {error && <p className="text-sm text-(--color-ledger-danger)">{error}</p>}
      <Button type="submit" disabled={isPending}>
        {isPending ? "Changing…" : "Change password"}
      </Button>
    </form>
  );
}
