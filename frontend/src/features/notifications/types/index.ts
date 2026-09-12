// API_SPEC.md / notifications.py's NotificationOut — read data, not form input, no Zod schema
// needed. Minimal on purpose: only the Dashboard's Issues Raised panel needs this right now
// (2026-09-13) — mark-read/polling UI is a separate, later Notifications screen
// (FRONTEND_ARCHITECTURE.md §1's own 11-screen inventory lists it apart from Dashboard).
export interface Notification {
  id: string;
  type: string;
  taskId: string | null;
  issueId: string | null;
  isRead: boolean;
  createdAt: string;
}
