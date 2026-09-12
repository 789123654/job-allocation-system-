import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { tenantQueryKey } from "@/lib/tenant-query-key";
import { toTask, type TaskOutDto } from "@/features/tasks/api/mappers";
import { useSession } from "@/stores/session-store";

export interface TaskFilters {
  status?: string;
  assignedTo?: string;
  jobTypeId?: string;
  taskType?: string;
}

// GET /tasks with Owner-only query filters (API_SPEC.md: ?status=/?assigned_to=/?job_type_id=/
// ?task_type=) — the Dashboard's All Tasks table / Awaiting Review panel (?status=submitted) /
// consolidated billing view (?task_type=billing). Distinct from get-tasks.ts's useMyTasks(),
// which deliberately sends no params at all — crud.list_tasks (re-read fresh this pass) ignores
// these filters entirely for a non-owner actor, applying them only when actor.role == "owner".
export function useAllTasks(filters: TaskFilters) {
  const { firmId } = useSession();
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.assignedTo) params.set("assigned_to", filters.assignedTo);
  if (filters.jobTypeId) params.set("job_type_id", filters.jobTypeId);
  if (filters.taskType) params.set("task_type", filters.taskType);
  const qs = params.toString();

  return useQuery({
    queryKey: [...tenantQueryKey("tasks", firmId), "all", filters],
    queryFn: () =>
      apiRequest<TaskOutDto[]>(`/tasks${qs ? `?${qs}` : ""}`).then((dtos) => dtos.map(toTask)),
    enabled: firmId !== null,
  });
}
