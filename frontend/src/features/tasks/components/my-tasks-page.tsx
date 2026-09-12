import { Link } from "react-router-dom";
import { useMyTasks } from "@/features/tasks/api/get-tasks";
import { useSession } from "@/stores/session-store";

// FRONTEND_ARCHITECTURE.md §1: "My Tasks (own pending + reassigned work)" — Employee only.
// job_type_id isn't resolved to a name here — TaskOut doesn't include one, and joining against
// useJobTypes() is a real enhancement, deliberately deferred (YAGNI) rather than scope-creeping
// this pass; Title/Status/Deadline is enough to open the right task.
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
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-(--color-ledger-border) text-left text-(--color-ledger-text-muted)">
            <th className="py-2 font-medium">Title</th>
            <th className="py-2 font-medium">Status</th>
            <th className="py-2 font-medium">Deadline</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={task.id} className="border-b border-(--color-ledger-border)">
              <td className="py-2">
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
              <td className="py-2 capitalize">{task.status.replace("_", " ")}</td>
              <td className="py-2">
                {task.deadline ? new Date(task.deadline).toLocaleDateString() : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
