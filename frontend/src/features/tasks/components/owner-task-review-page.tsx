import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useCreateTaskReview } from "@/features/tasks/api/create-task-review";
import { useTask } from "@/features/tasks/api/get-task";
import { taskReviewSchema, type TaskReviewInput } from "@/features/tasks/types";
import { ApiError } from "@/lib/api-client";

// PRD §2.6/§2.8: three review outcomes; the "billing" outcome's 5 fields (assignee, deadline,
// description, amount, recipient) are collected inline here rather than as a genuinely separate
// screen — FRONTEND_ARCHITECTURE.md's own "Billing Task Creation" row is this same POST
// /tasks/{id}/review call with outcome=billing, not a second endpoint (confirmed by re-reading
// tasks.py's review_task fresh this pass, not assumed from the screen inventory's naming).
export function OwnerTaskReviewPage({
  employeeOptions,
}: {
  employeeOptions: { id: string; label: string }[];
}) {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const { data: task, isPending, isError } = useTask(taskId ?? "");
  const createTaskReview = useCreateTaskReview();
  // Same "one key per task navigated to" shape as task-detail-page.tsx's fix earlier this
  // session — a plain useState lazy initializer, made to regenerate on navigation by the route
  // wrapper keying this component on taskId (router.tsx), not by a useMemo([taskId]) that
  // react-hooks/exhaustive-deps would flag for the same reason it did there.
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = useForm<TaskReviewInput>({
    resolver: zodResolver(taskReviewSchema),
    defaultValues: { outcome: "approved" },
  });
  const outcome = useWatch({ control, name: "outcome" });

  if (!taskId) return null;
  if (isPending) return <p className="text-sm text-(--color-ledger-text-muted)">Loading…</p>;
  if (isError || !task) {
    return <p className="text-sm text-(--color-ledger-danger)">Could not load this task.</p>;
  }

  async function onSubmit(input: TaskReviewInput) {
    if (!taskId) return;
    try {
      await createTaskReview.mutateAsync({ taskId, idempotencyKey, ...input });
      navigate("/");
    } catch {
      // createTaskReview.isError/.error already reflects this — rendered below.
    }
  }

  const errorMessage =
    createTaskReview.error instanceof ApiError && createTaskReview.error.status === 409
      ? "This task can't be reviewed from its current status — refresh and check again"
      : createTaskReview.isError
        ? "Something went wrong — try again"
        : null;

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl">{task.title}</h1>
      {task.description && (
        <p className="text-sm text-(--color-ledger-text-muted)">{task.description}</p>
      )}
      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
        <div>
          <Label htmlFor="outcome">Outcome</Label>
          <Controller
            control={control}
            name="outcome"
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger id="outcome">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="approved">Approve</SelectItem>
                  <SelectItem value="reassigned">Reassign</SelectItem>
                  <SelectItem value="billing">Billing</SelectItem>
                </SelectContent>
              </Select>
            )}
          />
        </div>
        <div>
          <Label htmlFor="notes">Notes</Label>
          <Input id="notes" {...register("notes")} />
        </div>
        {outcome === "reassigned" && (
          <>
            <div>
              <Label htmlFor="remainingWorkDescription">Remaining work</Label>
              <Input id="remainingWorkDescription" {...register("remainingWorkDescription")} />
              {errors.remainingWorkDescription && (
                <p className="mt-1 text-sm text-(--color-ledger-danger)">
                  {errors.remainingWorkDescription.message}
                </p>
              )}
            </div>
            <div>
              <Label htmlFor="assignedTo">Reassign to (optional)</Label>
              <Controller
                control={control}
                name="assignedTo"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="assignedTo">
                      <SelectValue placeholder="Keep current assignee" />
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
          </>
        )}
        {outcome === "billing" && (
          <>
            <div>
              <Label htmlFor="billingAssignedTo">Bill via</Label>
              <Controller
                control={control}
                name="assignedTo"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="billingAssignedTo">
                      <SelectValue placeholder="Choose an employee" />
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
              {errors.assignedTo && (
                <p className="mt-1 text-sm text-(--color-ledger-danger)">
                  {errors.assignedTo.message}
                </p>
              )}
            </div>
            <div>
              <Label htmlFor="billingDeadline">Billing deadline</Label>
              <Input id="billingDeadline" type="date" {...register("billingDeadline")} />
            </div>
            <div>
              <Label htmlFor="billingDescription">Billing description</Label>
              <Input id="billingDescription" {...register("billingDescription")} />
            </div>
            <div>
              <Label htmlFor="billingAmount">Billing amount</Label>
              <Input
                id="billingAmount"
                type="number"
                step="0.01"
                {...register("billingAmount", { valueAsNumber: true })}
              />
            </div>
            <div>
              <Label htmlFor="billingRecipient">Billing recipient</Label>
              <Input id="billingRecipient" {...register("billingRecipient")} />
            </div>
            {errors.outcome && (
              <p className="text-sm text-(--color-ledger-danger)">{errors.outcome.message}</p>
            )}
          </>
        )}
        {errorMessage && <p className="text-sm text-(--color-ledger-danger)">{errorMessage}</p>}
        <Button type="submit" disabled={createTaskReview.isPending}>
          {createTaskReview.isPending ? "Saving…" : "Submit review"}
        </Button>
      </form>
    </div>
  );
}
