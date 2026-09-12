import { z } from "zod";

// Mirrors backend/app/api/routes/tasks.py's IssueCreate exactly (description: NoNulStr,
// min_length=1, max_length=2000) — FRONTEND_ARCHITECTURE.md §7: the Zod schema is both the
// client-side validator and the TS request type, not maintained twice. Only this slice's own
// (Employee-side) form gets a schema here — TaskCreate/TaskReviewCreate/IssueResolveRequest are
// Owner-only, deferred to the next Tasks pass (CODING_STRUCTURE.md's one-vertical-slice-at-a-time
// discipline, per this session's own scoping decision).
export const raiseIssueSchema = z.object({
  description: z.string().min(1, "Description is required").max(2000, "Description is too long"),
});

export type RaiseIssueInput = z.infer<typeof raiseIssueSchema>;

// API_SPEC.md / tasks.py's TaskOut — full field set, since GET /tasks/{id} returns every field
// (including Owner-review-only ones like billing_amount/last_reassignment_*) to an Employee
// viewing their own task, not just the fields this pass's screens read. Read data, not form
// input, so no Zod schema needed.
export type TaskStatus =
  | "created"
  | "assigned"
  | "in_progress"
  | "submitted"
  | "completed"
  | "billed";

export interface Task {
  id: string;
  jobTypeId: string | null;
  taskType: string;
  parentTaskId: string | null;
  title: string;
  description: string | null;
  assignedTo: string | null;
  deadline: string | null;
  status: TaskStatus;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  lastReassignmentNotes: string | null;
  lastReassignmentRemainingWork: string | null;
  lastReassignmentSource: string | null;
  lastReassignmentAt: string | null;
  billingAmount: number | null;
  billingRecipient: string | null;
}

export interface Issue {
  id: string;
  taskId: string;
  raisedBy: string;
  description: string;
  status: string;
  resolutionType: string | null;
  resolutionNotes: string | null;
  remainingWorkDescription: string | null;
  resolvedBy: string | null;
  resolvedAt: string | null;
  createdAt: string;
}
