import type { TaskStatus } from "@/features/tasks/types";

// Mirrors backend/app/crud.py's _ACTIVE_TASK_STATUSES / _URGENT_WINDOW (the values behind the
// Owner-facing "task_deadline_1_day" / "task_overdue" notifications) — but ONLY the Owner's 1-day
// window, not crud.py's separate _APPROACHING_WINDOW (3 days) used for the assignee's own
// "task_deadline_approaching" notification. /code-review finding (2026-09-17): an earlier version
// of this comment claimed this "mirrors the backend exactly" for both roles, which overstated it —
// on My Tasks, a task 40h from its deadline already triggered the Employee's own 3-day notification
// but shows no highlight here (40h > 24h). This is a deliberate, user-instructed choice, not an
// oversight: the user asked for the same "1 day away" yellow threshold in both the Owner and
// Employee views, explicitly naming "1 day," not each role's own separate window — kept as stated,
// documented honestly here instead of silently reconciled to crud.py's dual thresholds.
//
// reported gap, 2026-09-17: the Owner/Employee dashboards had no visual cue at all for an
// approaching or missed deadline short of opening the Notifications page. ASVS 5 V8.3.1
// ("authorization enforced at a trusted service layer — never relies on client-side JS", checked
// this pass): this value is purely decorative and must never gate an action — nothing reads it to
// enable/disable a button or a request.
//
// ponytail: computed once per render off Date.now(), no timer/poll of its own — a row can go stale
// (e.g. stay "Due soon" past the real deadline) until something else re-renders the page. Add a
// refetchInterval/tick only if a stale decorative label past a page left open turns into a real
// complaint; not worth a polling timer for a cosmetic label at this pilot's scale.
const ACTIVE_STATUSES = new Set<TaskStatus>(["created", "assigned", "in_progress", "submitted"]);
const URGENT_WINDOW_MS = 24 * 60 * 60 * 1000;

export type DeadlineStatus = "overdue" | "urgent" | null;

export function deadlineStatus(task: { deadline: string | null; status: TaskStatus }): DeadlineStatus {
  if (!task.deadline || !ACTIVE_STATUSES.has(task.status)) return null;
  const msUntilDeadline = new Date(task.deadline).getTime() - Date.now();
  if (msUntilDeadline < 0) return "overdue";
  if (msUntilDeadline <= URGENT_WINDOW_MS) return "urgent";
  return null;
}

export function deadlineStatusLabel(status: DeadlineStatus): string | null {
  if (status === "overdue") return "Overdue";
  if (status === "urgent") return "Due soon";
  return null;
}

// row-level Tailwind classes — kept next to the status logic so every table applies the exact
// same visual meaning to "urgent"/"overdue" rather than each screen picking its own shade.
export function deadlineRowClassName(status: DeadlineStatus): string {
  if (status === "overdue") return "bg-(--color-ledger-danger)/15";
  if (status === "urgent") return "bg-(--color-ledger-warning)/20";
  return "";
}

export function deadlineTextClassName(status: DeadlineStatus): string {
  if (status === "overdue") return "text-(--color-ledger-danger)";
  if (status === "urgent") return "text-(--color-ledger-warning)";
  return "";
}
