import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useTask } from "@/features/tasks/api/get-task";
import { useMarkTaskBilled } from "@/features/tasks/api/mark-task-billed";
import { useSubmitTask } from "@/features/tasks/api/submit-task";
import { RaiseIssueDialog } from "@/features/tasks/components/raise-issue-dialog";
import { ApiError } from "@/lib/api-client";

// FRONTEND_ARCHITECTURE.md §1: "Task Detail & Submit (billing-type tasks: Mark Billed instead of
// Mark Completed)" — one screen, terminal button/action depends on task.taskType, not two screens
// (corrected 2026-09-02, same doc). Reachable only via My Tasks' own links (object-level-authz
// pattern already established: the id is never user-typed) — a direct URL to another employee's
// task still 404s server-side (get_task, tasks.py), surfaced here as the existing isError state.
export function TaskDetailPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const { data: task, isPending, isError } = useTask(taskId ?? "");
  const submitTask = useSubmitTask();
  const markTaskBilled = useMarkTaskBilled();

  // One Idempotency-Key per task navigated to (rest-api-guidelines Rule 230, re-read fresh this
  // pass). A plain useState(() => ...) lazy initializer only runs once per component *instance* —
  // it would NOT regenerate on its own if this component just re-rendered with a new taskId.
  // React Router's own remount behavior across a dynamic-segment change isn't documented in any
  // installed skill, so rather than depend on it: router.tsx renders this component keyed by
  // taskId (verified against react-official's preserving-and-resetting-state.md — a changed `key`
  // is React's own core guarantee of a full remount, not a react-router-specific behavior), which
  // makes this useState reliably re-run fresh for every task, with no dependency array to get
  // wrong (the react-hooks/exhaustive-deps warning a useMemo([taskId]) version triggered — the
  // factory body doesn't reference taskId, only the remount-forcing key does).
  const [idempotencyKey] = useState(() => crypto.randomUUID());

  if (!taskId) return null;
  if (isPending) return <p className="text-sm text-(--color-ledger-text-muted)">Loading…</p>;
  if (isError || !task) {
    return <p className="text-sm text-(--color-ledger-danger)">Could not load this task.</p>;
  }

  const canAct = task.status === "assigned" || task.status === "in_progress";
  const isBilling = task.taskType === "billing";
  const action = isBilling ? markTaskBilled : submitTask;
  // Same ApiError/.status check every other mutation in this codebase uses (create-employee-
  // dialog.tsx, create-job-type-dialog.tsx) — not a one-off regex-on-message shortcut.
  const errorMessage =
    action.error instanceof ApiError && action.error.status === 409
      ? "This task can't be actioned from its current status — refresh and check again"
      : action.isError
        ? "Something went wrong — try again"
        : null;

  async function handleAction() {
    if (!taskId) return;
    try {
      if (isBilling) {
        await markTaskBilled.mutateAsync({ taskId, idempotencyKey });
      } else {
        await submitTask.mutateAsync({ taskId, idempotencyKey });
      }
      navigate("/tasks");
    } catch {
      // action.isError already reflects this — rendered above.
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl">{task.title}</h1>
      {task.description && (
        <p className="text-sm text-(--color-ledger-text-muted)">{task.description}</p>
      )}
      <dl className="grid grid-cols-2 gap-2 text-sm">
        <dt className="text-(--color-ledger-text-muted)">Status</dt>
        <dd className="capitalize">{task.status.replace("_", " ")}</dd>
        <dt className="text-(--color-ledger-text-muted)">Deadline</dt>
        <dd>{task.deadline ? new Date(task.deadline).toLocaleDateString() : "—"}</dd>
      </dl>
      {task.lastReassignmentSource && (
        <div className="rounded-(--radius-ledger) border border-(--color-ledger-border) p-4 text-sm">
          <p className="font-medium">Reassigned</p>
          {task.lastReassignmentRemainingWork && <p>{task.lastReassignmentRemainingWork}</p>}
          {task.lastReassignmentNotes && (
            <p className="text-(--color-ledger-text-muted)">{task.lastReassignmentNotes}</p>
          )}
        </div>
      )}
      {errorMessage && <p className="text-sm text-(--color-ledger-danger)">{errorMessage}</p>}
      {canAct && (
        <div className="flex gap-2">
          <Button type="button" onClick={handleAction} disabled={action.isPending}>
            {action.isPending ? "Saving…" : isBilling ? "Mark billed" : "Mark completed"}
          </Button>
          <RaiseIssueDialog taskId={taskId} />
        </div>
      )}
    </div>
  );
}
