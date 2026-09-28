import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { tenantQueryKey, tenantQueryKeyPrefix } from "@/lib/tenant-query-key";
import type { Notification, NotificationType } from "@/features/notifications/types";
import { useSession } from "@/stores/session-store";

interface NotificationOutDto {
  id: string;
  type: NotificationType;
  task_id: string | null;
  issue_id: string | null;
  task_title: string | null;
  is_read: boolean;
  created_at: string;
}

function toNotification(dto: NotificationOutDto): Notification {
  return {
    id: dto.id,
    type: dto.type,
    taskId: dto.task_id,
    issueId: dto.issue_id,
    taskTitle: dto.task_title,
    isRead: dto.is_read,
    createdAt: dto.created_at,
  };
}

export const notificationsQueryKeyPrefix = tenantQueryKeyPrefix("notifications");

// GET /notifications — notifications.py. `unreadOnly` defaults true, matching the route's own
// server-side default (API_SPEC.md) and the Dashboard's Issues Raised panel's existing usage
// (unchanged by this pass); the dedicated Notifications screen passes `unreadOnly: false` to see
// full history. Polling per FRONTEND_ARCHITECTURE.md §8/§91 — refetchInterval/
// refetchIntervalInBackground confirmed against the installed @tanstack/react-query 5.102.8's own
// type declarations this pass, not assumed from memory (no installed skill documents this
// library). refetchIntervalInBackground: false since the Tauri window is the only "background"
// case that matters here (ARCHITECTURE.md §8's own reasoning) — no point polling while unfocused.
// `limit` added 2026-09-17 for the nav bar's unread-count badge (router.tsx) — every prior caller
// omits it and keeps getting the route's own default (LimitQuery: 20), unchanged. Capped at 100
// server-side (core/validation.py's LimitQuery: `le=100`) regardless of what's passed.
export function useNotifications(options: { unreadOnly?: boolean; limit?: number } = {}) {
  const { firmId } = useSession();
  const unreadOnly = options.unreadOnly ?? true;
  const params = new URLSearchParams();
  if (!unreadOnly) params.set("unread_only", "false");
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  const query = params.toString();
  return useQuery({
    queryKey: [...tenantQueryKey("notifications", firmId), { unreadOnly, limit: options.limit }],
    queryFn: () =>
      apiRequest<NotificationOutDto[]>(`/notifications${query ? `?${query}` : ""}`).then((dtos) =>
        dtos.map(toNotification),
      ),
    enabled: firmId !== null,
    refetchInterval: 45_000,
    refetchIntervalInBackground: false,
  });
}
