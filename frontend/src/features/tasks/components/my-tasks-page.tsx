import { Link } from "react-router-dom";
import { useMyTasks } from "@/features/tasks/api/get-tasks";
import {
  deadlineRowClassName,
  deadlineStatus,
  deadlineStatusLabel,
  deadlineTextClassName,
} from "@/features/tasks/utils/deadline-status";
import { useSession } from "@/stores/session-store";

// FRONTEND_ARCHITECTURE.md §1: "My Tasks (own pending + reassigned work)" — Employee only.
// job_type_id isn't resolved to a name here — TaskOut doesn't include one, and joining against
// useJobTypes() is a real enhancement, deliberately deferred (YAGNI) rather than scope-creeping
// this pass.
//
// Description column added 2026-09-17 (reported gap): the row title alone didn't tell an
// Employee what a task actually involves — they had to open every task individually to find out.
// TaskDetailPage already shows the full description once opened; this adds a preview on the list
// itself, same truncate+title tooltip pattern as owner-dashboard-page.tsx's All Tasks table.
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
    return <p className="text-sm text-(--color-ledger-text-muted)">No tasks assigned yet.</p>;
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
          {tasks.map((task) => {
            const dueStatus = deadlineStatus(task);
            const dueLabel = deadlineStatusLabel(dueStatus);
            return (
              <tr
                key={task.id}
                className={`hover:bg-(--color-ledger-border)/40 ${deadlineRowClassName(dueStatus)}`}
              >
                <td className="truncate border border-(--color-ledger-border) px-3 py-2">
                  <Link
                    to={`/tasks/${task.id}`}
                    className="text-(--color-ledger-accent) hover:underline"
                  >
                    {task.title}
                  </Link>
                  {task.lastReassignmentSource && (
                    <span className="ml-2 text-xs text-(--color-ledger-text-muted)">
                      (reassigned)
                    </span>
                  )}
                </td>
                <td
                  className="truncate border border-(--color-ledger-border) px-3 py-2"
                  title={task.description ?? undefined}
                >
                  {task.description ?? "—"}
                </td>
                <td className="truncate border border-(--color-ledger-border) px-3 py-2 capitalize">
                  {task.status.replace("_", " ")}
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
          })}
        </tbody>
      </table>
    </div>
  );
}
