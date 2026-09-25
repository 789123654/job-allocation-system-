import type { QueryClient } from "@tanstack/react-query";
import { tasksQueryKeyPrefix } from "@/features/tasks/api/get-tasks";
import { tenantQueryKeyPrefix } from "@/lib/tenant-query-key";

// Shared by every task-mutating hook (code-review finding #1, 2026-09-14) — a task mutation can
// change which employee a task counts against for the Employees list's pendingJobCount, not just
// the task itself, so both keys always need invalidating together. Before this extraction, each
// hook hand-rolled its own onSuccess; the employees invalidation was added only to resolve-issue.ts
// (written after the bug was found), and never propagated to the 4 pre-existing sibling hooks
// (create-task/submit-task/mark-task-billed/create-task-review) — the exact stale-pendingTaskCount
// bug this shared helper closes for all 5 by construction, not by remembering to copy the fix.
export function invalidateAfterTaskMutation(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: tasksQueryKeyPrefix });
  void queryClient.invalidateQueries({ queryKey: tenantQueryKeyPrefix("employees") });
}
