import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { tenantQueryKey, tenantQueryKeyPrefix } from "@/lib/tenant-query-key";
import { toTask, type TaskOutDto } from "@/features/tasks/api/mappers";
import type { Task } from "@/features/tasks/types";
import { useSession } from "@/stores/session-store";

export const tasksQueryKeyPrefix = tenantQueryKeyPrefix("tasks");

// API_SPEC.md / tasks.py: GET /tasks. crud.list_tasks (read directly, not assumed) is
// role-scoped server-side, not just filtered — an Employee's results are always their own
// (Task.assigned_to == actor.id) regardless of what query params are sent, since the Owner-only
// filters (status/assigned_to/job_type_id/task_type) are ignored entirely for a non-owner actor.
// So this hook (the Employee-facing "My Tasks" list) sends no params at all — the backend's own
// role check is what makes this "my tasks", not a client-side filter the client could get wrong.
function getMyTasks(): Promise<Task[]> {
  return apiRequest<TaskOutDto[]>("/tasks").then((dtos) => dtos.map(toTask));
}

export function useMyTasks() {
  const { firmId } = useSession();
  return useQuery({
    queryKey: tenantQueryKey("tasks", firmId),
    queryFn: getMyTasks,
    enabled: firmId !== null,
  });
}
