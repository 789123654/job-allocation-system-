import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { tasksQueryKeyPrefix } from "@/features/tasks/api/get-tasks";
import { toTask, type TaskOutDto } from "@/features/tasks/api/mappers";
import type { Task, TaskCreateInput } from "@/features/tasks/types";

// POST /tasks — tasks.py's create_task. Real Idempotency-Key required (API_SPEC.md: "the
// strongest of the three patterns, since accidental duplicate task creation is the clearest harm
// here") — unlike create_employee/create_job_type, which dedup via a DB unique constraint
// instead. Owner-only server-side (RequireOwnerDep); this hook has no client-side role check of
// its own, matching every other resource in this codebase (server enforces, UI just doesn't show
// the button to an Employee).
function createTask(input: TaskCreateInput & { idempotencyKey: string }): Promise<Task> {
  return apiRequest<TaskOutDto>("/tasks", {
    method: "POST",
    idempotencyKey: input.idempotencyKey,
    body: {
      title: input.title,
      description: input.description ?? null,
      job_type_id: input.jobTypeId ?? null,
      assigned_to: input.assignedTo ?? null,
      deadline: input.deadline ?? null,
    },
  }).then(toTask);
}

export function useCreateTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createTask,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: tasksQueryKeyPrefix });
    },
  });
}
