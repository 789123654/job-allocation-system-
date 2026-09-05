import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSetNewPassword } from "@/features/auth/hooks/use-set-new-password";
import { passwordChangeSchema, type PasswordChangeInput } from "@/features/auth/types";

export function SetNewPasswordForm() {
  const { setNewPassword, error, isPending } = useSetNewPassword();
  const navigate = useNavigate();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<PasswordChangeInput>({ resolver: zodResolver(passwordChangeSchema) });

  async function onSubmit(input: PasswordChangeInput) {
    const success = await setNewPassword(input);
    if (success) {
      navigate("/", { replace: true });
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex w-full max-w-sm flex-col gap-4">
      <p className="text-sm text-(--color-ledger-text-muted)">
        You're using a temporary password. Set a new one to continue.
      </p>
      <div>
        <Label htmlFor="currentPassword">Temporary password</Label>
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
        {isPending ? "Setting password…" : "Set password"}
      </Button>
    </form>
  );
}
