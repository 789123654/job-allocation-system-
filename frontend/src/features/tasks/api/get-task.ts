import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { tenantQueryKey } from "@/lib/tenant-query-key";
import { toTask, type TaskOutDto } from "@/features/tasks/api/mappers";
import { useSession } from "@/stores/session-store";

// GET /tasks/{id} — tasks.py:246-249. taskId is appended after the tenant-scoped prefix (not a
// separate resource name) so tasksQueryKeyPrefix's plain ["tasks"] invalidation (TanStack Query's
// default prefix/fuzzy matching, same as every other slice) still matches this specific item's
// key too — one invalidateQueries call after submit/mark-billed refreshes both the list and any
// open detail view, without needing to know which one is currently mounted.
export function useTask(taskId: string) {
  const { firmId } = useSession();
  return useQuery({
    queryKey: [...tenantQueryKey("tasks", firmId), taskId],
    queryFn: () => apiRequest<TaskOutDto>(`/tasks/${taskId}`).then(toTask),
    enabled: firmId !== null,
  });
}
