import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateEmployee } from "@/features/employees/api/create-employee";
import { employeeCreateSchema, type EmployeeCreateInput } from "@/features/employees/types";
import { ApiError } from "@/lib/api-client";

export function CreateEmployeeDialog() {
  const [open, setOpen] = useState(false);
  // OWASP MFA Cheat Sheet's OTP-handling guidance applied to this one-time generated password:
  // single-use, never logged, and cleared from state (not just hidden) once the dialog closes.
  const [generatedPassword, setGeneratedPassword] = useState<string | null>(null);
  const createEmployee = useCreateEmployee();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<EmployeeCreateInput>({ resolver: zodResolver(employeeCreateSchema) });

  function onOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      setGeneratedPassword(null);
      reset();
      createEmployee.reset();
    }
  }

  async function onSubmit(input: EmployeeCreateInput) {
    try {
      const result = await createEmployee.mutateAsync(input);
      setGeneratedPassword(result.generatedPassword);
      reset();
    } catch {
      // createEmployee.isError/.error already reflects this — rendered below.
    }
  }

  const errorMessage =
    createEmployee.error instanceof ApiError && createEmployee.error.status === 409
      ? "Email already in use"
      : createEmployee.isError
        ? "Something went wrong — try again"
        : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button type="button">+ Add employee</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogTitle>{generatedPassword ? "Employee added" : "Add employee"}</DialogTitle>
        {generatedPassword ? (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-(--color-ledger-text-muted)">
              Share this temporary password with the employee directly — it is shown only this
              once and cannot be retrieved again.
            </p>
            <Input
              readOnly
              value={generatedPassword}
              onFocus={(e) => e.currentTarget.select()}
              className="font-(family-name:--font-mono)"
            />
            <Button type="button" onClick={() => onOpenChange(false)}>
              Done
            </Button>
          </div>
        ) : (
          <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
            <div>
              <Label htmlFor="fullName">Full name</Label>
              <Input id="fullName" {...register("fullName")} />
              {errors.fullName && (
                <p className="mt-1 text-sm text-(--color-ledger-danger)">
                  {errors.fullName.message}
                </p>
              )}
            </div>
            <div>
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" {...register("email")} />
              {errors.email && (
                <p className="mt-1 text-sm text-(--color-ledger-danger)">{errors.email.message}</p>
              )}
            </div>
            {errorMessage && (
              <p className="text-sm text-(--color-ledger-danger)">{errorMessage}</p>
            )}
            <Button type="submit" disabled={createEmployee.isPending}>
              {createEmployee.isPending ? "Adding…" : "Add employee"}
            </Button>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
