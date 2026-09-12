import { Link, useSearchParams } from "react-router-dom";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useEmployees } from "@/features/employees/api/get-employees";
import { useJobTypes } from "@/features/job-types/api/get-job-types";
import { useNotifications } from "@/features/notifications/api/get-notifications";
import { useAllTasks, type TaskFilters } from "@/features/tasks/api/get-all-tasks";
import { useIssue } from "@/features/tasks/api/get-issue";
import { CreateTaskDialog } from "@/features/tasks/components/create-task-dialog";
import type { Task } from "@/features/tasks/types";

// Owner Dashboard (PRD §2.4, FRONTEND_ARCHITECTURE.md §1) — the one place features/tasks,
// features/employees, features/job-types, and features/notifications compose together
// (FRONTEND_ARCHITECTURE.md §2: "features cannot import each other" — this lives in app/, not
// any one feature, specifically because it needs all four). URL-based filter state
// (FRONTEND_ARCHITECTURE.md §3: "Task list filters... React Router's search params — the URL *is*
// the filter state"), not local useState.
const ALL = "all";

export function OwnerDashboardPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const filters: TaskFilters = {
    status: searchParams.get("status") ?? undefined,
    assignedTo: searchParams.get("assigned_to") ?? undefined,
    jobTypeId: searchParams.get("job_type_id") ?? undefined,
    taskType: searchParams.get("task_type") ?? undefined,
  };

  const { data: tasks } = useAllTasks(filters);
  const { data: employees } = useEmployees();
  const { data: jobTypes } = useJobTypes();
  const { data: notifications } = useNotifications();

  const employeeName = new Map((employees ?? []).map((e) => [e.id, e.fullName]));
  const jobTypeName = new Map((jobTypes ?? []).map((jt) => [jt.id, jt.name]));
  const jobTypeOptions = (jobTypes ?? []).map((jt) => ({ id: jt.id, label: jt.name }));
  const employeeOptions = (employees ?? []).map((e) => ({ id: e.id, label: e.fullName }));

  const awaitingReview = (tasks ?? []).filter((t) => t.status === "submitted");
  const issueNotifications = (notifications ?? []).filter((n) => n.type === "issue_raised");

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(searchParams);
    if (value === ALL || !value) next.delete(key);
    else next.set(key, value);
    setSearchParams(next);
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl">Dashboard</h1>
        <CreateTaskDialog jobTypeOptions={jobTypeOptions} employeeOptions={employeeOptions} />
      </div>

      {employees && employees.length > 0 && (
        <section>
          <h2 className="mb-2 text-lg font-medium">Workload</h2>
          <ul className="flex flex-col gap-1 text-sm">
            {employees.map((e) => (
              <li key={e.id}>
                {e.fullName}: {e.pendingTaskCount} pending
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h2 className="mb-2 text-lg font-medium">Awaiting Review ({awaitingReview.length})</h2>
        <ul className="flex flex-col gap-1 text-sm">
          {awaitingReview.map((t) => (
            <li key={t.id}>
              <Link to={`/owner-tasks/${t.id}/review`} className="hover:underline">
                {t.title}
              </Link>
            </li>
          ))}
        </ul>
      </section>

      {issueNotifications.length > 0 && (
        <section>
          <h2 className="mb-2 text-lg font-medium">Issues Raised ({issueNotifications.length})</h2>
          <ul className="flex flex-col gap-1 text-sm">
            {issueNotifications.map((n) => (
              <IssueRow
                key={n.id}
                issueId={n.issueId}
                taskTitle={n.taskId ? ((tasks ?? []).find((t) => t.id === n.taskId)?.title ?? n.taskId) : "—"}
              />
            ))}
          </ul>
        </section>
      )}

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-lg font-medium">All Tasks</h2>
          <div className="flex gap-2">
            <Select value={filters.status ?? ALL} onValueChange={(v) => setFilter("status", v)}>
              <SelectTrigger id="status-filter" aria-label="Filter by status" className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All statuses</SelectItem>
                <SelectItem value="created">Created</SelectItem>
                <SelectItem value="assigned">Assigned</SelectItem>
                <SelectItem value="in_progress">In progress</SelectItem>
                <SelectItem value="submitted">Submitted</SelectItem>
                <SelectItem value="completed">Completed</SelectItem>
                <SelectItem value="billed">Billed</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={filters.taskType ?? ALL}
              onValueChange={(v) => setFilter("task_type", v)}
            >
              <SelectTrigger id="task-type-filter" aria-label="Filter by task type" className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All task types</SelectItem>
                <SelectItem value="standard">Standard</SelectItem>
                <SelectItem value="billing">Billing</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-(--color-ledger-text-muted)">
              <th className="font-normal">Title</th>
              <th className="font-normal">Job type</th>
              <th className="font-normal">Assignee</th>
              <th className="font-normal">Status</th>
              <th className="font-normal">Deadline</th>
            </tr>
          </thead>
          <tbody>
            {(tasks ?? []).map((t: Task) => (
              <tr key={t.id}>
                <td>
                  <Link to={`/owner-tasks/${t.id}/review`} className="hover:underline">
                    {t.title}
                  </Link>
                </td>
                <td>{t.jobTypeId ? (jobTypeName.get(t.jobTypeId) ?? "—") : "—"}</td>
                <td>{t.assignedTo ? (employeeName.get(t.assignedTo) ?? "—") : "Unassigned"}</td>
                <td className="capitalize">{t.status.replace("_", " ")}</td>
                <td>{t.deadline ? new Date(t.deadline).toLocaleDateString() : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function IssueRow({ issueId, taskTitle }: { issueId: string | null; taskTitle: string }) {
  const { data: issue } = useIssue(issueId ?? "");
  return (
    <li>
      <span className="font-medium">{taskTitle}:</span> {issue?.description ?? "Loading…"}
    </li>
  );
}
