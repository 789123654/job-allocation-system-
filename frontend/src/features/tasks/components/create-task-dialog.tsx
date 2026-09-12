import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useCreateTask } from "@/features/tasks/api/create-task";
import { taskCreateSchema, type TaskCreateInput } from "@/features/tasks/types";
import { ApiError } from "@/lib/api-client";

// features/tasks cannot import features/job-types or features/employees directly
// (FRONTEND_ARCHITECTURE.md §2: "features cannot import each other" — enforced by ESLint's
// import/no-restricted-paths) — so job-type/employee options are passed in as plain {id,label}
// props, fetched and mapped by whichever app/-level page composes this dialog with those two
// features. Not the Dashboard yet (deferred, this session's own scoping decision) — this
// component is self-contained and tested standalone until that composition point exists.
interface Option {
  id: string;
  label: string;
}

export function CreateTaskDialog({
  jobTypeOptions,
  employeeOptions,
}: {
  jobTypeOptions: Option[];
  employeeOptions: Option[];
}) {
  const [open, setOpen] = useState(false);
  // Real Idempotency-Key (API_SPEC.md: task creation is "the strongest of the three patterns"),
  // regenerated on close — same boundary as raise-issue-dialog.tsx, not the useMemo([taskId])
  // pattern task-detail-page.tsx had to move away from (that was for a key that must survive
  // re-renders of the same instance; this is a key scoped to one dialog-open attempt instead).
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());
  const createTask = useCreateTask();
  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors },
  } = useForm<TaskCreateInput>({ resolver: zodResolver(taskCreateSchema) });

  function onOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      reset();
      createTask.reset();
      setIdempotencyKey(crypto.randomUUID());
    }
  }

  async function onSubmit(input: TaskCreateInput) {
    try {
      await createTask.mutateAsync({ ...input, idempotencyKey });
      onOpenChange(false);
    } catch {
      // createTask.isError/.error already reflects this — rendered below.
    }
  }

  const errorMessage =
    createTask.error instanceof ApiError && createTask.error.status === 422
      ? "Assignee must be an active employee, and job type must be active"
      : createTask.isError
        ? "Something went wrong — try again"
        : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button type="button">+ New task</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogTitle>New task</DialogTitle>
        <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
          <div>
            <Label htmlFor="title">Title</Label>
            <Input id="title" {...register("title")} />
            {errors.title && (
              <p className="mt-1 text-sm text-(--color-ledger-danger)">{errors.title.message}</p>
            )}
          </div>
          <div>
            <Label htmlFor="description">Description</Label>
            <Input id="description" {...register("description")} />
            {errors.description && (
              <p className="mt-1 text-sm text-(--color-ledger-danger)">
                {errors.description.message}
              </p>
            )}
          </div>
          {jobTypeOptions.length > 0 && (
            <div>
              <Label htmlFor="jobTypeId">Job type</Label>
              <Controller
                control={control}
                name="jobTypeId"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="jobTypeId">
                      <SelectValue placeholder="No job type" />
                    </SelectTrigger>
                    <SelectContent>
                      {jobTypeOptions.map((option) => (
                        <SelectItem key={option.id} value={option.id}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </div>
          )}
          {employeeOptions.length > 0 && (
            <div>
              <Label htmlFor="assignedTo">Assign to</Label>
              <Controller
                control={control}
                name="assignedTo"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="assignedTo">
                      <SelectValue placeholder="Unassigned" />
                    </SelectTrigger>
                    <SelectContent>
                      {employeeOptions.map((option) => (
                        <SelectItem key={option.id} value={option.id}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </div>
          )}
          <div>
            <Label htmlFor="deadline">Deadline</Label>
            <Input id="deadline" type="date" {...register("deadline")} />
          </div>
          {errorMessage && <p className="text-sm text-(--color-ledger-danger)">{errorMessage}</p>}
          <Button type="submit" disabled={createTask.isPending}>
            {createTask.isPending ? "Creating…" : "Create task"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
