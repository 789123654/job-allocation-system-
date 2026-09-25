import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { notificationsQueryKeyPrefix } from "@/features/notifications/api/get-notifications";
import type { Notification, NotificationType } from "@/features/notifications/types";

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

// PATCH /notifications/{id}/read — notifications.py's mark_notification_read. No Idempotency-Key
// header: unlike every mutating POST elsewhere in this codebase, this route takes no
// idempotency_key param at all — API_SPEC.md notes it's "naturally idempotent" (marking read
// twice has the same effect), confirmed by reading the route's real signature this pass rather
// than assumed from the sibling mutation hooks' Idempotency-Key pattern.
function markNotificationRead(notificationId: string): Promise<Notification> {
  return apiRequest<NotificationOutDto>(`/notifications/${notificationId}/read`, {
    method: "PATCH",
  }).then(toNotification);
}

export function useMarkNotificationRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: markNotificationRead,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: notificationsQueryKeyPrefix });
    },
  });
}
