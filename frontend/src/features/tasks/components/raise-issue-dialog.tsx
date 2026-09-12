import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateTaskIssue } from "@/features/tasks/api/create-task-issue";
import { raiseIssueSchema, type RaiseIssueInput } from "@/features/tasks/types";

// Idempotency-Key generated once per dialog-open attempt, same boundary as
// reset-password-dialog.tsx — reused across retries within one attempt, a fresh one on
// close/reopen (a deliberate second attempt, not a network retry).
export function RaiseIssueDialog({ taskId }: { taskId: string }) {
  const [open, setOpen] = useState(false);
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());
  const createIssue = useCreateTaskIssue();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<RaiseIssueInput>({ resolver: zodResolver(raiseIssueSchema) });

  function onOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      reset();
      createIssue.reset();
      setIdempotencyKey(crypto.randomUUID());
    }
  }

  async function onSubmit(input: RaiseIssueInput) {
    try {
      await createIssue.mutateAsync({ taskId, idempotencyKey, description: input.description });
      onOpenChange(false);
    } catch {
      // createIssue.isError/.error already reflects this — rendered below.
    }
  }

  const errorMessage = createIssue.isError ? "Something went wrong — try again" : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button type="button" variant="ghost">
          Raise issue
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogTitle>Raise an issue</DialogTitle>
        <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
          <div>
            <Label htmlFor="description">What's the issue?</Label>
            <Input id="description" {...register("description")} />
            {errors.description && (
              <p className="mt-1 text-sm text-(--color-ledger-danger)">
                {errors.description.message}
              </p>
            )}
          </div>
          {errorMessage && <p className="text-sm text-(--color-ledger-danger)">{errorMessage}</p>}
          <Button type="submit" disabled={createIssue.isPending}>
            {createIssue.isPending ? "Submitting…" : "Submit"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
