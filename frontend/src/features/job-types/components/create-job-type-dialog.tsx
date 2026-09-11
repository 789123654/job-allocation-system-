import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateJobType } from "@/features/job-types/api/create-job-type";
import { jobTypeCreateSchema, type JobTypeCreateInput } from "@/features/job-types/types";
import { ApiError } from "@/lib/api-client";

// Simpler than CreateEmployeeDialog — no generated-password state, since a job type has no
// credential to show once. Closes immediately on success instead of showing a confirmation step.
export function CreateJobTypeDialog() {
  const [open, setOpen] = useState(false);
  const createJobType = useCreateJobType();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<JobTypeCreateInput>({ resolver: zodResolver(jobTypeCreateSchema) });

  function onOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      reset();
      createJobType.reset();
    }
  }

  async function onSubmit(input: JobTypeCreateInput) {
    try {
      await createJobType.mutateAsync(input);
      // Route through onOpenChange, not setOpen(false) directly — that's the one place close-
      // cleanup (createJobType.reset()) lives. Found during this slice's security audit: an
      // earlier version called setOpen(false) here, skipping that cleanup. Checked with a
      // negative-control test whether this is observable like reset-password-dialog.tsx's
      // close-cleanup gap (mutation testing, earlier this session) — it is NOT: nothing in this
      // component reads createJobType.data/.isSuccess, and .error is already null on a success
      // path regardless, so the test passed identically with the bug present and was removed as
      // misleading rather than kept. Fixed anyway for consistency with the single-close-path
      // invariant every other dialog in this codebase follows, and as defense against a future
      // edit that reads .data/.isSuccess without re-adding this.
      onOpenChange(false);
    } catch {
      // createJobType.isError/.error already reflects this — rendered below.
    }
  }

  const errorMessage =
    createJobType.error instanceof ApiError && createJobType.error.status === 409
      ? "Job type name already in use"
      : createJobType.isError
        ? "Something went wrong — try again"
        : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button type="button">+ Add job type</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogTitle>Add job type</DialogTitle>
        <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
          <div>
            <Label htmlFor="name">Name</Label>
            <Input id="name" {...register("name")} />
            {errors.name && (
              <p className="mt-1 text-sm text-(--color-ledger-danger)">{errors.name.message}</p>
            )}
          </div>
          {errorMessage && <p className="text-sm text-(--color-ledger-danger)">{errorMessage}</p>}
          <Button type="submit" disabled={createJobType.isPending}>
            {createJobType.isPending ? "Adding…" : "Add job type"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
