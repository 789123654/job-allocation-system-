import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { invalidateAfterTaskMutation } from "@/features/tasks/api/invalidate-after-task-mutation";
import { toTask, type TaskOutDto } from "@/features/tasks/api/mappers";
import type { Task } from "@/features/tasks/types";

// PATCH /tasks/{task_id} — tasks.py's edit_task. Owner-only server-side (RequireOwnerDep). Only
// the keys present in `changes` are sent: a key that is absent means "leave it alone", so the
// caller must not send an unchanged assigned_to (crud.edit_task validates the assignee before it
// checks for a real change, so an unchanged assignee who was since deactivated would 422 a
// title-only save). No Idempotency-Key on this route, matching the backend.
export interface TaskEditChanges {
  title?: string;
  description?: string | null;
  assigned_to?: string;
}

function editTask(input: { taskId: string; changes: TaskEditChanges }): Promise<Task> {
  return apiRequest<TaskOutDto>(`/tasks/${input.taskId}`, {
    method: "PATCH",
    body: input.changes,
  }).then(toTask);
}

export function useEditTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: editTask,
    onSuccess: () => invalidateAfterTaskMutation(queryClient),
  });
}
