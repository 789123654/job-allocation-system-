import { useParams } from "react-router-dom";
import { useIssue } from "@/features/tasks/api/get-issue";
import { useTask } from "@/features/tasks/api/get-task";

// Reported gap, 2026-09-18: an Employee received an "issue resolved" notification but clicking it
// only ever opened TaskDetailPage — which has no idea an issue even exists (Task carries no issue
// reference), so the Owner's actual resolution_notes were unreachable. Backend companion fix:
// GET /issues/{id} widened from Owner-only to the issue's raiser too (crud.get_issue). Read-only —
// resolving is still Owner-only (IssueResolutionPage, /owner-issues/:issueId/resolve); this is the
// symmetric read-side view for the person who raised it.
function resolutionTypeLabel(resolutionType: string): string {
  switch (resolutionType) {
    case "clarified":
      return "Clarified";
    case "deadline_adjusted":
      return "Deadline adjusted";
    case "reassigned":
      return "Reassigned";
    default:
      return resolutionType;
  }
}

export function IssueDetailPage() {
  const { issueId } = useParams<{ issueId: string }>();
  const { data: issue, isPending, isError } = useIssue(issueId ?? "");
  const { data: task } = useTask(issue?.taskId ?? "");

  if (!issueId) return null;
  if (isPending) return <p className="text-sm text-(--color-ledger-text-muted)">Loading…</p>;
  if (isError || !issue) {
    return <p className="text-sm text-(--color-ledger-danger)">Could not load this issue.</p>;
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl">{task?.title ?? "Issue"}</h1>
      <div>
        <h2 className="text-sm font-medium text-(--color-ledger-text-muted)">You raised</h2>
        <p className="mt-1 text-sm">{issue.description}</p>
      </div>
      {issue.status === "resolved" ? (
        <div className="rounded-(--radius-ledger) border border-(--color-ledger-border) p-4">
          <h2 className="text-sm font-medium text-(--color-ledger-text-muted)">
            {issue.resolutionType ? resolutionTypeLabel(issue.resolutionType) : "Resolved"}
          </h2>
          {issue.resolutionNotes && <p className="mt-1 text-sm">{issue.resolutionNotes}</p>}
          {issue.remainingWorkDescription && (
            <p className="mt-2 text-sm text-(--color-ledger-text-muted)">
              Remaining work: {issue.remainingWorkDescription}
            </p>
          )}
        </div>
      ) : (
        <p className="text-sm text-(--color-ledger-text-muted)">Awaiting the owner's response.</p>
      )}
    </div>
  );
}
