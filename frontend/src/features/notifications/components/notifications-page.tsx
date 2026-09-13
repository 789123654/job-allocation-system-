import { Link } from "react-router-dom";
import { useMarkNotificationRead } from "@/features/notifications/api/mark-notification-read";
import { useNotifications } from "@/features/notifications/api/get-notifications";
import { notificationMessage, type Notification } from "@/features/notifications/types";
import { useSession } from "@/stores/session-store";

// PRD §2.5/§3.4/§4.4 — the 11th and final Phase 4 screen, both roles (FRONTEND_ARCHITECTURE.md §1).
// Full history (unreadOnly: false), not just the unread list the Dashboard's Issues Raised panel
// uses — this is the one screen meant for browsing past notifications, not just the current
// unread count, so YAGNI doesn't apply the same way here.
export function NotificationsPage() {
  const { role } = useSession();
  const { data: notifications } = useNotifications({ unreadOnly: false });
  const markRead = useMarkNotificationRead();

  function targetPath(n: Notification): string | null {
    if (n.type === "issue_raised" && n.issueId) return `/owner-issues/${n.issueId}/resolve`;
    if (!n.taskId) return null;
    return role === "owner" ? `/owner-tasks/${n.taskId}/review` : `/tasks/${n.taskId}`;
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl">Notifications</h1>
      <ul className="flex flex-col gap-2">
        {(notifications ?? []).map((n) => {
          const path = targetPath(n);
          const message = notificationMessage(n.type);
          // PRD §2.5: task_deadline_1_day is a distinct, visually highlighted warning, separate
          // from the general "approaching deadline" view — not just another list row.
          const isUrgent = n.type === "task_deadline_1_day";
          return (
            <li
              key={n.id}
              className={
                "flex items-center justify-between gap-4 rounded-(--radius-ledger) border p-3 text-sm " +
                (isUrgent
                  ? "border-(--color-ledger-danger) bg-(--color-ledger-danger)/10"
                  : "border-(--color-ledger-border)") +
                (n.isRead ? " text-(--color-ledger-text-muted)" : " font-medium")
              }
            >
              {path ? (
                <Link to={path} className="hover:underline">
                  {message}
                </Link>
              ) : (
                <span>{message}</span>
              )}
              {!n.isRead && (
                <button
                  type="button"
                  onClick={() => markRead.mutate(n.id)}
                  className="shrink-0 text-xs text-(--color-ledger-text-muted) hover:underline"
                >
                  Mark read
                </button>
              )}
            </li>
          );
        })}
      </ul>
      {notifications?.length === 0 && (
        <p className="text-sm text-(--color-ledger-text-muted)">No notifications.</p>
      )}
    </div>
  );
}
