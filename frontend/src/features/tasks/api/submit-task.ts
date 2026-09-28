import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { invalidateAfterTaskMutation } from "@/features/tasks/api/invalidate-after-task-mutation";
import { toTask, type TaskOutDto } from "@/features/tasks/api/mappers";
import type { Task } from "@/features/tasks/types";

// POST /tasks/{id}/submit — tasks.py:261-283. Real Idempotency-Key required (IdempotencyKeyHeader
// param on the route, unlike create_employee/create_job_type which dedup via a unique DB
// constraint instead). rest-api-guidelines Rule 230 (re-read fresh this pass): the same key must
// be reused across retries of ONE logical operation — the caller (task-detail-page.tsx) generates
// it once per task-page-view via useState, remounted per taskId via router.tsx's TaskDetailRoute
// `key` prop, matching reset-password-dialog.tsx's established "one key per attempt" boundary,
// adapted from "per dialog-open" to "per task navigated to".
function submitTask(input: { taskId: string; idempotencyKey: string }): Promise<Task> {
  return apiRequest<TaskOutDto>(`/tasks/${input.taskId}/submit`, {
    method: "POST",
    idempotencyKey: input.idempotencyKey,
  }).then(toTask);
}

export function useSubmitTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: submitTask,
    onSuccess: () => invalidateAfterTaskMutation(queryClient),
  });
}
