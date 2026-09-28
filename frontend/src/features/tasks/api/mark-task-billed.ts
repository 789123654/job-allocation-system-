import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { invalidateAfterTaskMutation } from "@/features/tasks/api/invalidate-after-task-mutation";
import { toTask, type TaskOutDto } from "@/features/tasks/api/mappers";
import type { Task } from "@/features/tasks/types";

// POST /tasks/{id}/mark-billed — tasks.py:286-309. Same Idempotency-Key reasoning as
// submit-task.ts. PRD §4.2 / FRONTEND_ARCHITECTURE.md §1: this is task-detail-page.tsx's terminal
// action instead of Submit when task.taskType === "billing" — same screen, different button.
function markTaskBilled(input: { taskId: string; idempotencyKey: string }): Promise<Task> {
  return apiRequest<TaskOutDto>(`/tasks/${input.taskId}/mark-billed`, {
    method: "POST",
    idempotencyKey: input.idempotencyKey,
  }).then(toTask);
}

export function useMarkTaskBilled() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: markTaskBilled,
    onSuccess: () => invalidateAfterTaskMutation(queryClient),
  });
}
