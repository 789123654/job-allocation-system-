import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { tasksQueryKeyPrefix } from "@/features/tasks/api/get-tasks";
import { toIssue, type IssueOutDto } from "@/features/tasks/api/mappers";
import type { Issue } from "@/features/tasks/types";

// POST /tasks/{id}/issues — tasks.py:360-389. Real Idempotency-Key required, same reasoning as
// submit-task.ts. No GET /issues or GET /tasks/{id}/issues endpoint exists (grepped issues.py and
// tasks.py fresh this pass) — raising an issue doesn't change task.status (crud.create_issue,
// read directly), so invalidating the tasks cache here is precautionary consistency, not because
// this response changes anything the task list/detail displays yet.
function createTaskIssue(input: {
  taskId: string;
  description: string;
  idempotencyKey: string;
}): Promise<Issue> {
  return apiRequest<IssueOutDto>(`/tasks/${input.taskId}/issues`, {
    method: "POST",
    idempotencyKey: input.idempotencyKey,
    body: { description: input.description },
  }).then(toIssue);
}

export function useCreateTaskIssue() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createTaskIssue,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: tasksQueryKeyPrefix });
    },
  });
}
