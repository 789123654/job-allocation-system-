import { Link, useSearchParams } from "react-router-dom";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useEmployees } from "@/features/employees/api/get-employees";
import { useJobTypes } from "@/features/job-types/api/get-job-types";
import { useNotifications } from "@/features/notifications/api/get-notifications";
import { useAllTasks, type TaskFilters } from "@/features/tasks/api/get-all-tasks";
import { useIssue } from "@/features/tasks/api/get-issue";
import { CreateTaskDialog } from "@/features/tasks/components/create-task-dialog";
import type { Task } from "@/features/tasks/types";
import {
  deadlineRowClassName,
  deadlineStatus,
  deadlineStatusLabel,
  deadlineTextClassName,
} from "@/features/tasks/utils/deadline-status";

// Owner Dashboard (PRD §2.4, FRONTEND_ARCHITECTURE.md §1) — the one place features/tasks,
// features/employees, features/job-types, and features/notifications compose together
// (FRONTEND_ARCHITECTURE.md §2: "features cannot import each other" — this lives in app/, not
// any one feature, specifically because it needs all four). URL-based filter state
// (FRONTEND_ARCHITECTURE.md §3: "Task list filters... React Router's search params — the URL *is*
// the filter state"), not local useState.
const ALL = "all";

export function OwnerDashboardPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  // task_type (Standard/Billing) dropped from this page's filters (2026-09-17, user's explicit
  // call): it duplicated Job Type for this page's purpose without adding a distinct axis an Owner
  // actually wanted to filter by here. useAllTasks/TaskFilters still accept it (it's a real,
  // unrelated field on Task — task-detail-page.tsx uses it to pick "Mark billed" vs "Mark
  // completed" — untouched), this page just no longer sends it.
  const filters: TaskFilters = {
    status: searchParams.get("status") ?? undefined,
    assignedTo: searchParams.get("assigned_to") ?? undefined,
    jobTypeId: searchParams.get("job_type_id") ?? undefined,
  };

  // Two separate fetches, deliberately not one shared list: Awaiting Review and Issues Raised
  // must always reflect every task regardless of what the Owner has selected in the All Tasks
  // filter — found by an independent code-review pass (2026-09-13) after both panels were
  // previously derived from the same filtered list, so e.g. filtering All Tasks to "billing"
  // silently hid an unrelated submitted task from Awaiting Review too. `allTasks` feeds those two
  // panels; `filteredTasks` feeds only the All Tasks table itself.
  const { data: allTasks } = useAllTasks({});
  const { data: filteredTasks } = useAllTasks(filters);
  const { data: employees } = useEmployees();
  const { data: jobTypes } = useJobTypes();
  // limit: 100 (2026-09-17) — same fix as router.tsx's NotificationsNavLink badge. The route's own
  // default is 20 (notifications.py); left unset, Issues Raised silently truncated once a firm had
  // >20 unread notifications of ANY type mixed in (deadline reminders included) — the same shape
  // of bug as the 2026-09-13 code-review finding on this exact file (a caller reaching a default
  // limit with nothing visible showing rows were cut). 100 is the route's own hard max
  // (core/validation.py's LimitQuery le=100).
  const { data: notifications } = useNotifications({ limit: 100 });

  const employeeName = new Map((employees ?? []).map((e) => [e.id, e.fullName]));
  const jobTypeName = new Map((jobTypes ?? []).map((jt) => [jt.id, jt.name]));
  const jobTypeOptions = (jobTypes ?? []).map((jt) => ({ id: jt.id, label: jt.name }));
  // PRD §"See each employee's current workload (pending-job count), to support load-balancing at
  // assignment time" — the Workload section below already shows this, but the assignment picker
  // itself didn't, so the count wasn't visible at the actual decision point (reported gap,
  // 2026-09-16).
  const employeeOptions = (employees ?? []).map((e) => ({
    id: e.id,
    label: `${e.fullName} (${e.pendingTaskCount} pending)`,
  }));

  const awaitingReview = (allTasks ?? []).filter((t) => t.status === "submitted");
  const issueNotifications = (notifications ?? []).filter((n) => n.type === "issue_raised");

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(searchParams);
    if (value === ALL || !value) next.delete(key);
    else next.set(key, value);
    setSearchParams(next);
  }

  // /code-review finding (2026-09-17): a plain `to="?status=submitted"` Link silently dropped any
  // other active All Tasks filter (e.g. task_type=billing) instead of merging into it, unlike every
  // other filter change here, which goes through setFilter's `new URLSearchParams(searchParams)`
  // merge. This builds the same merged query string setFilter would produce, so "View all" really
  // is filter-additive, not filter-replacing.
  const awaitingReviewParams = new URLSearchParams(searchParams);
  awaitingReviewParams.set("status", "submitted");
  const awaitingReviewHref = awaitingReviewParams.toString();

  return (
    <div className="flex flex-col gap-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl">Dashboard</h1>
        <CreateTaskDialog jobTypeOptions={jobTypeOptions} employeeOptions={employeeOptions} />
      </div>

      {/* Restructured 2026-09-17 (reported gap): as tasks/issues accumulate, these panels used to
          render as bare bullet lists with no boundary, no bound on growth, and no separation from
          each other — the exact "untidy as it grows" concern raised for this page. Each panel is
          now a bordered card matching the All Tasks table's own boundary language; Awaiting Review
          collapses to a count + a "View all" link into the All Tasks table itself (reusing the
          exact same `setFilter`/searchParams mechanism the status Select already uses below — not
          a new filter mechanism), since every submitted task it would have listed is already
          reachable there. Issues Raised has no equivalent full-list page to link to yet (only
          GET/POST /issues/{id}, no list endpoint — confirmed by re-reading routes/issues.py this
          pass), so it keeps its per-item list but bounded to a scrollable max-height card instead
          of an unbounded one. */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {employees && employees.length > 0 && (
          <section className="rounded-(--radius-ledger) border border-(--color-ledger-border) p-4">
            <h2 className="text-lg font-medium">Workload</h2>
            <ul className="mt-2 flex max-h-48 flex-col gap-1 overflow-y-auto text-sm">
              {employees.map((e) => (
                <li key={e.id}>
                  {e.fullName}: {e.pendingTaskCount} pending
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="rounded-(--radius-ledger) border border-(--color-ledger-border) p-4">
          <h2 className="text-lg font-medium">Awaiting Review ({awaitingReview.length})</h2>
          {awaitingReview.length > 0 ? (
            <Link
              to={`?${awaitingReviewHref}`}
              className="mt-2 inline-block text-sm text-(--color-ledger-accent) hover:underline"
            >
              View all →
            </Link>
          ) : (
            <p className="mt-2 text-sm text-(--color-ledger-text-muted)">Nothing awaiting review</p>
          )}
        </section>

        {issueNotifications.length > 0 && (
          <section className="rounded-(--radius-ledger) border border-(--color-ledger-border) p-4">
            <h2 className="text-lg font-medium">Issues Raised ({issueNotifications.length})</h2>
            <ul className="mt-2 flex max-h-48 flex-col gap-1 overflow-y-auto text-sm">
              {issueNotifications.map((n) => (
                <IssueRow
                  key={n.id}
                  issueId={n.issueId}
                  taskTitle={n.taskId ? ((allTasks ?? []).find((t) => t.id === n.taskId)?.title ?? n.taskId) : "—"}
                />
              ))}
            </ul>
          </section>
        )}
      </div>

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
            {/* Reported gap, 2026-09-17: filters.jobTypeId/useAllTasks already accepted job_type_id
                (get-all-tasks.ts's own ?job_type_id= param), and jobTypeOptions was already built
                above for CreateTaskDialog — this control just never existed, so there was no way
                to filter by the Owner's own job types, only by the unrelated Standard/Billing task
                type. */}
            <Select
              value={filters.jobTypeId ?? ALL}
              onValueChange={(v) => setFilter("job_type_id", v)}
            >
              <SelectTrigger id="job-type-filter" aria-label="Filter by job type" className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All job types</SelectItem>
                {jobTypeOptions.map((jt) => (
                  <SelectItem key={jt.id} value={jt.id}>
                    {jt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <table className="w-full table-fixed border-collapse border border-(--color-ledger-border) text-sm">
          <colgroup>
            <col className="w-[18%]" />
            <col className="w-[28%]" />
            <col className="w-[14%]" />
            <col className="w-[14%]" />
            <col className="w-[12%]" />
            <col className="w-[14%]" />
          </colgroup>
          <thead>
            <tr className="text-left text-(--color-ledger-text-muted)">
              <th className="border border-(--color-ledger-border) px-3 py-2 font-normal">
                Title
              </th>
              <th className="border border-(--color-ledger-border) px-3 py-2 font-normal">
                Description
              </th>
              <th className="border border-(--color-ledger-border) px-3 py-2 font-normal">
                Job type
              </th>
              <th className="border border-(--color-ledger-border) px-3 py-2 font-normal">
                Assignee
              </th>
              <th className="border border-(--color-ledger-border) px-3 py-2 font-normal">
                Status
              </th>
              <th className="border border-(--color-ledger-border) px-3 py-2 font-normal">
                Deadline
              </th>
            </tr>
          </thead>
          <tbody>
            {(filteredTasks ?? []).map((t: Task) => {
              const dueStatus = deadlineStatus(t);
              const dueLabel = deadlineStatusLabel(dueStatus);
              // Reported gap, 2026-09-17: an Owner had no visual flag at all for "this task is
              // submitted and awaiting my review" in the table itself — only the Status column's
              // plain text, and the separate Awaiting Review count card above. Deadline urgency
              // still wins when both apply (an overdue-but-submitted task is more urgent than a
              // plain "needs review" one), so this only kicks in when deadlineStatus found nothing.
              const rowClassName = dueStatus
                ? deadlineRowClassName(dueStatus)
                : t.status === "submitted"
                  ? "bg-(--color-ledger-accent)/10"
                  : "";
              return (
                <tr key={t.id} className={`hover:bg-(--color-ledger-border)/40 ${rowClassName}`}>
                  <td className="truncate border border-(--color-ledger-border) px-3 py-2" title={t.title}>
                    <Link to={`/owner-tasks/${t.id}/review`} className="hover:underline">
                      {t.title}
                    </Link>
                  </td>
                  <td
                    className="truncate border border-(--color-ledger-border) px-3 py-2"
                    title={t.description ?? undefined}
                  >
                    {t.description ?? "—"}
                  </td>
                  <td
                    className="truncate border border-(--color-ledger-border) px-3 py-2"
                    title={t.jobTypeId ? (jobTypeName.get(t.jobTypeId) ?? undefined) : undefined}
                  >
                    {t.jobTypeId ? (jobTypeName.get(t.jobTypeId) ?? "—") : "—"}
                  </td>
                  <td
                    className="truncate border border-(--color-ledger-border) px-3 py-2"
                    title={t.assignedTo ? (employeeName.get(t.assignedTo) ?? undefined) : undefined}
                  >
                    {t.assignedTo ? (employeeName.get(t.assignedTo) ?? "—") : "Unassigned"}
                  </td>
                  <td className="truncate border border-(--color-ledger-border) px-3 py-2 capitalize">
                    {t.status.replace("_", " ")}
                  </td>
                  <td className="truncate border border-(--color-ledger-border) px-3 py-2">
                    {t.deadline ? new Date(t.deadline).toLocaleDateString() : "—"}
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
      </section>
    </div>
  );
}

function IssueRow({ issueId, taskTitle }: { issueId: string | null; taskTitle: string }) {
  const { data: issue } = useIssue(issueId ?? "");
  return (
    <li>
      {issueId ? (
        <Link to={`/owner-issues/${issueId}/resolve`} className="font-medium hover:underline">
          {taskTitle}
        </Link>
      ) : (
        <span className="font-medium">{taskTitle}</span>
      )}
      : {issue?.description ?? "Loading…"}
    </li>
  );
}
