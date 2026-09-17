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
    // Same fix as the sibling issue-resolution-page.tsx (code-review finding, whole-Phase-4 sweep,
    // 2026-09-13): without this, react-hook-form keeps a conditionally-rendered field's value in
    // form state after its input unmounts, so switching outcome away from a partially-filled
    // "reassigned"/"billing" branch leaves a stale value that trips taskReviewSchema's own
    // combination guard and silently blocks submission.
    shouldUnregister: true,
  });
  const outcome = useWatch({ control, name: "outcome" });

  if (!taskId) return null;
  if (isPending) return <p className="text-sm text-(--color-ledger-text-muted)">Loading…</p>;
  if (isError || !task) {
    return <p className="text-sm text-(--color-ledger-danger)">Could not load this task.</p>;
  }
  // Code-review finding (whole-Phase-4 sweep, 2026-09-13): every entry point (deadline/overdue
  // notifications, the All Tasks table) links here regardless of status, but review_task only
  // succeeds for "submitted" — surfacing that as a 409 only at submit time let an Owner fill out
  // an entire form for a task that was never reviewable. Pre-check instead.
  //
  // Reported gap, 2026-09-17: the pre-check above was right to block the form, but bailing out to
  // a bare one-line message left every non-"submitted" entry point (deadline notifications, the
  // All Tasks table) as a dead end with no task context at all — an Owner clicking a "due in 1
  // day" notification just hit "not awaiting review" and nothing else, since there's no separate
  // general-purpose task detail view for Owners the way TaskDetailPage is for Employees. Showing
  // the task's own info here instead (title/description/status/assignee/deadline, all already
  // fetched via useTask above) turns this into a real destination instead of a dead end, while
  // still refusing to render the review FORM for anything but "submitted" — same guarantee the
  // 2026-09-13 regression test already covers via the "isn't awaiting review" text this keeps.
  if (task.status !== "submitted") {
    const assigneeLabel = task.assignedTo
      ? (employeeOptions.find((e) => e.id === task.assignedTo)?.label ?? "Unknown")
      : "Unassigned";
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl">{task.title}</h1>
        {task.description && (
          <p className="text-sm text-(--color-ledger-text-muted)">{task.description}</p>
        )}
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-(--color-ledger-text-muted)">Status</dt>
          <dd className="capitalize">{task.status.replace("_", " ")}</dd>
          <dt className="text-(--color-ledger-text-muted)">Assigned to</dt>
          <dd>{assigneeLabel}</dd>
          <dt className="text-(--color-ledger-text-muted)">Deadline</dt>
          <dd>{task.deadline ? new Date(task.deadline).toLocaleDateString() : "—"}</dd>
        </dl>
        <p className="text-sm text-(--color-ledger-danger)">
          This task isn't awaiting review yet — it becomes reviewable once the employee submits
          it.
        </p>
      </div>
    );
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
      : createTaskReview.error instanceof ApiError && createTaskReview.error.status === 422
        ? "The chosen assignee is not an active employee of this firm"
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
          {errors.outcome && (
            <p className="mt-1 text-sm text-(--color-ledger-danger)">{errors.outcome.message}</p>
          )}
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
              {errors.assignedTo && (
                <p className="mt-1 text-sm text-(--color-ledger-danger)">
                  {errors.assignedTo.message}
                </p>
              )}
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
              {errors.billingDeadline && (
                <p className="mt-1 text-sm text-(--color-ledger-danger)">
                  {errors.billingDeadline.message}
                </p>
              )}
            </div>
            <div>
              <Label htmlFor="billingDescription">Billing description</Label>
              <Input id="billingDescription" {...register("billingDescription")} />
              {errors.billingDescription && (
                <p className="mt-1 text-sm text-(--color-ledger-danger)">
                  {errors.billingDescription.message}
                </p>
              )}
            </div>
            <div>
              <Label htmlFor="billingAmount">Billing amount</Label>
              <Input
                id="billingAmount"
                type="number"
                step="0.01"
                {...register("billingAmount", { valueAsNumber: true })}
              />
              {errors.billingAmount && (
                <p className="mt-1 text-sm text-(--color-ledger-danger)">
                  {errors.billingAmount.message}
                </p>
              )}
            </div>
            <div>
              <Label htmlFor="billingRecipient">Billing recipient</Label>
              <Input id="billingRecipient" {...register("billingRecipient")} />
              {errors.billingRecipient && (
                <p className="mt-1 text-sm text-(--color-ledger-danger)">
                  {errors.billingRecipient.message}
                </p>
              )}
            </div>
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
