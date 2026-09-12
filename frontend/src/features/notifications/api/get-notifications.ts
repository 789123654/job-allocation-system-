import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { tenantQueryKey } from "@/lib/tenant-query-key";
import type { Notification } from "@/features/notifications/types";
import { useSession } from "@/stores/session-store";

interface NotificationOutDto {
  id: string;
  type: string;
  task_id: string | null;
  issue_id: string | null;
  is_read: boolean;
  created_at: string;
}

function toNotification(dto: NotificationOutDto): Notification {
  return {
    id: dto.id,
    type: dto.type,
    taskId: dto.task_id,
    issueId: dto.issue_id,
    isRead: dto.is_read,
    createdAt: dto.created_at,
  };
}

// GET /notifications — notifications.py. No polling/mark-read here (YAGNI, deferred to the
// dedicated Notifications screen) — the Dashboard's Issues Raised panel just needs the current
// unread list once per page load, same as any other TanStack Query read.
export function useNotifications() {
  const { firmId } = useSession();
  return useQuery({
    queryKey: tenantQueryKey("notifications", firmId),
    queryFn: () =>
      apiRequest<NotificationOutDto[]>("/notifications").then((dtos) => dtos.map(toNotification)),
    enabled: firmId !== null,
  });
}
