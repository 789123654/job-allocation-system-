import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { dateOnlyToEndOfDayIso } from "@/lib/date-only-to-instant";
import { tenantQueryKeyPrefix } from "@/lib/tenant-query-key";
import { invalidateAfterTaskMutation } from "@/features/tasks/api/invalidate-after-task-mutation";
import { toIssue, type IssueOutDto } from "@/features/tasks/api/mappers";
import type { Issue, IssueResolveInput } from "@/features/tasks/types";

// POST /issues/{id}/resolve — issues.py's resolve_issue, IdempotencyKeyHeader required (same
// pattern as create-task-review.ts). Field names mirror IssueResolveRequest exactly;
// issueResolveSchema's superRefine already stops an invalid combination from reaching this call.
function resolveIssue(
  input: { issueId: string; idempotencyKey: string } & IssueResolveInput,
): Promise<Issue> {
  return apiRequest<IssueOutDto>(`/issues/${input.issueId}/resolve`, {
    method: "POST",
    idempotencyKey: input.idempotencyKey,
    body: {
      resolution_type: input.resolutionType,
      resolution_notes: input.resolutionNotes,
      new_deadline: input.newDeadline ? dateOnlyToEndOfDayIso(input.newDeadline) : null,
      assigned_to: input.assignedTo ?? null,
      remaining_work_description: input.remainingWorkDescription ?? null,
    },
  }).then(toIssue);
}

export function useResolveIssue() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: resolveIssue,
    onSuccess: () => {
      invalidateAfterTaskMutation(queryClient);
      // Issues Raised (Owner Dashboard) is driven by useNotifications() filtered on
      // type==="issue_raised" — without this, a resolved issue stays visible there forever since
      // resolving it never marks the originating notification read (code-review finding, whole-
      // Phase-4 sweep, 2026-09-13).
      void queryClient.invalidateQueries({ queryKey: tenantQueryKeyPrefix("notifications") });
    },
  });
}
