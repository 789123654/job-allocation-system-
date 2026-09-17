// API_SPEC.md / notifications.py's NotificationOut — read data, not form input, no Zod schema
// needed. The 8 type values below mirror DATA_MODEL.md §5's table exactly (its own 1:1 mapping
// to PRD §2.5/§3.4 bullets), re-read fresh this pass rather than assumed from the bare `type:
// string` this interface had when only the Dashboard's Issues Raised panel consumed it.
export type NotificationType =
  | "task_submitted"
  | "task_overdue"
  | "task_deadline_1_day"
  | "issue_raised"
  | "task_assigned"
  | "task_reassigned"
  | "task_deadline_approaching"
  | "task_overdue_own";

export interface Notification {
  id: string;
  type: NotificationType;
  taskId: string | null;
  issueId: string | null;
  // Reported gap, 2026-09-17: notifications gave no reference to which task they were about —
  // backend now resolves this via a batch title lookup (crud.get_task_titles); null when the
  // notification has no task_id (shouldn't happen in practice — every type sets one — or if the
  // task lookup somehow misses, which this type has to allow for regardless).
  taskTitle: string | null;
  isRead: boolean;
  createdAt: string;
}

// PRD §2.5: "Task is exactly 1 day from deadline — a distinct, visually highlighted warning,
// separate from the general 'approaching deadline' view" — the one type-specific UI requirement
// the PRD states explicitly, so it's centralized here rather than left to each consumer to notice.
// taskTitle interpolated in, 2026-09-17 — falls back to the old generic wording when null (no
// task_id on the notification, or the lookup missed) rather than rendering a broken "" reference.
export function notificationMessage(type: NotificationType, taskTitle: string | null): string {
  const task = taskTitle ? `"${taskTitle}"` : "a task";
  switch (type) {
    case "task_submitted":
      return `An employee submitted ${task} for review`;
    case "task_overdue":
      return `${taskTitle ? `"${taskTitle}"` : "A task"} is overdue`;
    case "task_deadline_1_day":
      return `${taskTitle ? `"${taskTitle}"` : "A task"} is due in 1 day`;
    case "issue_raised":
      return `An employee raised an issue on ${task}`;
    case "task_assigned":
      return `You were assigned ${task}`;
    case "task_reassigned":
      return `${taskTitle ? `"${taskTitle}"` : "A task"} was reassigned to you`;
    case "task_deadline_approaching":
      return `${taskTitle ? `"${taskTitle}"` : "A task"} is approaching its deadline`;
    case "task_overdue_own":
      return `Your task ${task} is overdue`;
  }
}
