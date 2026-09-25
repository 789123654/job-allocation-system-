import { useState } from "react";
import { Link } from "react-router-dom";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useMarkNotificationRead } from "@/features/notifications/api/mark-notification-read";
import { useNotifications } from "@/features/notifications/api/get-notifications";
import { notificationMessage, type Notification } from "@/features/notifications/types";
import { useMarkTaskBilled } from "@/features/tasks/api/mark-task-billed";
import { useSubmitTask } from "@/features/tasks/api/submit-task";
import { useMyTasks } from "@/features/tasks/api/get-tasks";
import { RaiseIssueDialog } from "@/features/tasks/components/raise-issue-dialog";
import type { Task } from "@/features/tasks/types";
import {
  deadlineRowClassName,
  deadlineStatus,
  deadlineStatusLabel,
  deadlineTextClassName,
} from "@/features/tasks/utils/deadline-status";
import { ApiError } from "@/lib/api-client";
import { useSession } from "@/stores/session-store";

// Reported gap, 2026-09-18: an Employee only ever saw "issue resolved" / "task reassigned" /
// "deadline approaching" / "own task overdue" by opening the Notifications tab — easy to never do,
// so a real update (e.g. the Owner resolving a raised issue) could sit unseen indefinitely. Same
// data these already have (useNotifications, already used by owner-dashboard-page.tsx's Issues
// Raised panel) surfaced directly on the Employee's own main screen instead. Deliberately excludes
// task_assigned/task_submitted/issue_raised/task_deadline_1_day/task_overdue — the first three
// don't apply to this role or are covered elsewhere (a new assignment is already visible as a new
// row in the table below), and task_deadline_1_day/task_overdue are the Owner's own thresholds
// (deadline-status.ts's own comment: this app deliberately mirrors only the Owner's 1-day window
// for row highlighting, not the assignee's separate 3-day one — same distinction applies here).
const EMPLOYEE_NOTIFICATION_TYPES = new Set<Notification["type"]>([
  "task_deadline_approaching",
  "task_overdue_own",
  "task_reassigned",
  "issue_resolved",
]);

function NotificationsBox() {
  // limit: 100, same reasoning as owner-dashboard-page.tsx's Issues Raised panel (route default
  // is 20 — silently truncates once mixed with other notification types past that).
  const { data: notifications } = useNotifications({ limit: 100 });
  const markRead = useMarkNotificationRead();
  const relevant = (notifications ?? []).filter((n) => EMPLOYEE_NOTIFICATION_TYPES.has(n.type));

  if (relevant.length === 0) return null;

  return (
    <section className="rounded-(--radius-ledger) border border-(--color-ledger-border) p-4">
      <h2 className="text-lg font-medium">Notifications ({relevant.length})</h2>
      <ul className="mt-2 flex max-h-48 flex-col gap-1 overflow-y-auto text-sm">
        {relevant.map((n) => {
          // Reported gap, 2026-09-18: issue_resolved used to link to TaskDetailPage, which has no
          // idea an issue exists — the Owner's resolution_notes were unreachable. IssueDetailPage
          // (GET /issues/{id}, now reachable by the raiser) is the actual answer to "what did the
          // owner say", same fix as notifications-page.tsx's targetPath().
          const path =
            n.type === "issue_resolved" && n.issueId
              ? `/issues/${n.issueId}`
              : n.taskId
                ? `/tasks/${n.taskId}`
                : null;
          return (
            <li key={n.id} className="flex items-center justify-between gap-4">
              {path ? (
                <Link to={path} className="hover:underline">
                  {notificationMessage(n.type, n.taskTitle)}
                </Link>
              ) : (
                <span>{notificationMessage(n.type, n.taskTitle)}</span>
              )}
              <button
                type="button"
                onClick={() => markRead.mutate(n.id)}
                className="shrink-0 text-xs text-(--color-ledger-text-muted) hover:underline"
              >
                Mark read
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// FRONTEND_ARCHITECTURE.md §1: "My Tasks (own pending + reassigned work)" — Employee only.
// job_type_id isn't resolved to a name here — TaskOut doesn't include one, and joining against
// useJobTypes() is a real enhancement, deliberately deferred (YAGNI) rather than scope-creeping
// this pass.
//
// Description column added 2026-09-17 (reported gap): the row title alone didn't tell an
// Employee what a task actually involves — they had to open every task individually to find out.
// TaskDetailPage already shows the full description once opened; this adds a preview on the list
// itself, same truncate+title tooltip pattern as owner-dashboard-page.tsx's All Tasks table.
//
// Status cell reworked 2026-09-17 (reported gap, two parts): (1) "Assigned" reads Owner-centric —
// an Employee's own worklist calls the same state "Pending" instead, same underlying TaskStatus
// value, display label only. (2) Mark completed/billed + Raise issue were only reachable via
// TaskDetailPage, which itself was only reachable via a small, easy-to-miss title link — this
// folds both actions into the Status cell as a DropdownMenu (same interaction shape as this app's
// other pickers: click, choose, closes), removing the need for a separate Action column or a trip
// through Notifications.
function employeeStatusLabel(status: Task["status"]): string {
  return status === "assigned" ? "Pending" : status.replace("_", " ");
}

function TaskRow({ task }: { task: Task }) {
  const submitTask = useSubmitTask();
  const markTaskBilled = useMarkTaskBilled();
  // Same "one Idempotency-Key per task, reused across retries within one attempt" boundary as
  // task-detail-page.tsx — scoped per-row here since each row now performs this action inline
  // rather than after a navigation-triggered remount.
  const [idempotencyKey] = useState(() => crypto.randomUUID());

  const dueStatus = deadlineStatus(task);
  const dueLabel = deadlineStatusLabel(dueStatus);
  const canAct = task.status === "assigned" || task.status === "in_progress";
  const isBilling = task.taskType === "billing";
  const action = isBilling ? markTaskBilled : submitTask;
  const errorMessage =
    action.error instanceof ApiError && action.error.status === 409
      ? "This task can't be actioned from its current status — refresh and check again"
      : action.isError
        ? "Something went wrong — try again"
        : null;

  async function handleAction() {
    try {
      if (isBilling) {
        await markTaskBilled.mutateAsync({ taskId: task.id, idempotencyKey });
      } else {
        await submitTask.mutateAsync({ taskId: task.id, idempotencyKey });
      }
    } catch {
      // action.isError already reflects this — rendered below.
    }
  }

  return (
    <tr className={`hover:bg-(--color-ledger-border)/40 ${deadlineRowClassName(dueStatus)}`}>
      <td className="truncate border border-(--color-ledger-border) px-3 py-2">
        <Link to={`/tasks/${task.id}`} className="text-(--color-ledger-accent) hover:underline">
          {task.title}
        </Link>
        {task.lastReassignmentSource && (
          <span className="ml-2 text-xs text-(--color-ledger-text-muted)">(reassigned)</span>
        )}
      </td>
      <td
        className="truncate border border-(--color-ledger-border) px-3 py-2"
        title={task.description ?? undefined}
      >
        {task.description ?? "—"}
      </td>
      <td className="border border-(--color-ledger-border) px-3 py-2">
        {canAct ? (
          <DropdownMenu>
            <DropdownMenuTrigger className="capitalize underline decoration-dotted underline-offset-4">
              {employeeStatusLabel(task.status)}
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuItem onSelect={handleAction} disabled={action.isPending}>
                {action.isPending ? "Saving…" : isBilling ? "Mark billed" : "Mark completed"}
              </DropdownMenuItem>
              {/* preventDefault stops Radix from closing/unmounting this menu on select, which
                  would otherwise tear down RaiseIssueDialog's own Dialog before it can open. */}
              <DropdownMenuItem onSelect={(event) => event.preventDefault()} className="p-0">
                <RaiseIssueDialog taskId={task.id} />
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : (
          <span className="capitalize">{employeeStatusLabel(task.status)}</span>
        )}
        {errorMessage && <p className="mt-1 text-xs text-(--color-ledger-danger)">{errorMessage}</p>}
      </td>
      <td className="truncate border border-(--color-ledger-border) px-3 py-2">
        {task.deadline ? new Date(task.deadline).toLocaleDateString() : "—"}
        {dueLabel && (
          <span className={`ml-1 text-xs font-medium ${deadlineTextClassName(dueStatus)}`}>
            ({dueLabel})
          </span>
        )}
      </td>
    </tr>
  );
}

export function MyTasksPage() {
  const { data: tasks, isPending, isError } = useMyTasks();
  const { firmId, isLoading: isSessionLoading } = useSession();

  // Same firmId-null guard as employee-list.tsx/job-type-list.tsx (Employees-slice security
  // audit) — without this, a malformed/stale JWT missing app_metadata.firm_id would show an
  // infinite "Loading…" spinner instead of an error.
  if (!isSessionLoading && firmId === null) {
    return (
      <p className="text-sm text-(--color-ledger-danger)">
        Could not determine your firm — try signing out and back in.
      </p>
    );
  }

  if (isPending) return <p className="text-sm text-(--color-ledger-text-muted)">Loading…</p>;
  if (isError) {
    return (
      <p className="text-sm text-(--color-ledger-danger)">Could not load tasks — try again.</p>
    );
  }
  if (tasks.length === 0) {
    return (
      <div className="flex flex-col gap-6">
        <p className="text-sm text-(--color-ledger-text-muted)">No tasks assigned yet.</p>
        <NotificationsBox />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl">My tasks</h1>
      <table className="w-full table-fixed border-collapse border border-(--color-ledger-border) text-sm">
        <colgroup>
          <col className="w-[25%]" />
          <col className="w-[35%]" />
          <col className="w-[20%]" />
          <col className="w-[20%]" />
        </colgroup>
        <thead>
          <tr className="text-left text-(--color-ledger-text-muted)">
            <th className="border border-(--color-ledger-border) px-3 py-2 font-normal">Title</th>
            <th className="border border-(--color-ledger-border) px-3 py-2 font-normal">Description</th>
            <th className="border border-(--color-ledger-border) px-3 py-2 font-normal">Status</th>
            <th className="border border-(--color-ledger-border) px-3 py-2 font-normal">Deadline</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <TaskRow key={task.id} task={task} />
          ))}
        </tbody>
      </table>
      <NotificationsBox />
    </div>
  );
}
