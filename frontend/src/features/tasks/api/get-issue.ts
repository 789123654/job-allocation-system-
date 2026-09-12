import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { tenantQueryKey } from "@/lib/tenant-query-key";
import { toIssue, type IssueOutDto } from "@/features/tasks/api/mappers";
import { useSession } from "@/stores/session-store";

// GET /issues/{id} — added 2026-09-12 (issues.py) specifically for the Dashboard's "Issues
// Raised" panel, which otherwise only has {type, task_id, issue_id} from GET /notifications with
// no description text. Distinct tenant-query-key resource string ("issues") from "tasks", so
// invalidating one never accidentally matches the other via TanStack's prefix matching.
export function useIssue(issueId: string) {
  const { firmId } = useSession();
  return useQuery({
    queryKey: [...tenantQueryKey("issues", firmId), issueId],
    queryFn: () => apiRequest<IssueOutDto>(`/issues/${issueId}`).then(toIssue),
    enabled: firmId !== null,
  });
}
