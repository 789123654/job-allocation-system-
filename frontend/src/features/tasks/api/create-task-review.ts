import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { invalidateAfterTaskMutation } from "@/features/tasks/api/invalidate-after-task-mutation";
import { toTask, type TaskOutDto } from "@/features/tasks/api/mappers";
import type { Task, TaskReviewInput } from "@/features/tasks/types";

// POST /tasks/{id}/review — tasks.py's review_task, IdempotencyKeyHeader required (rest-api-
// guidelines Rule 230, same pattern already established for submit/mark-billed/issues). Field
// names below mirror TaskReviewCreate exactly, including which ones are only meaningful for
// which outcome — taskReviewSchema's superRefine already stops an invalid combination from ever
// reaching this call, so no additional validation here.
function createTaskReview(
  input: { taskId: string; idempotencyKey: string } & TaskReviewInput,
): Promise<Task> {
  return apiRequest<TaskOutDto>(`/tasks/${input.taskId}/review`, {
    method: "POST",
    idempotencyKey: input.idempotencyKey,
    body: {
      outcome: input.outcome,
      notes: input.notes ?? null,
      remaining_work_description: input.remainingWorkDescription ?? null,
      assigned_to: input.assignedTo ?? null,
      billing_deadline: input.billingDeadline ?? null,
      billing_description: input.billingDescription ?? null,
      billing_amount: input.billingAmount ?? null,
      billing_recipient: input.billingRecipient ?? null,
    },
  }).then(toTask);
}

export function useCreateTaskReview() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createTaskReview,
    onSuccess: () => invalidateAfterTaskMutation(queryClient),
  });
}
