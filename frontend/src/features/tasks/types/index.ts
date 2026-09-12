import { z } from "zod";

// Mirrors backend/app/api/routes/tasks.py's IssueCreate exactly (description: NoNulStr,
// min_length=1, max_length=2000) — FRONTEND_ARCHITECTURE.md §7: the Zod schema is both the
// client-side validator and the TS request type, not maintained twice.
export const raiseIssueSchema = z.object({
  description: z.string().min(1, "Description is required").max(2000, "Description is too long"),
});

export type RaiseIssueInput = z.infer<typeof raiseIssueSchema>;

// Mirrors tasks.py's TaskCreate exactly (title 1-300, description optional 0-5000).
export const taskCreateSchema = z.object({
  title: z.string().min(1, "Title is required").max(300, "Title is too long"),
  description: z.string().max(5000, "Description is too long").optional(),
  jobTypeId: z.string().uuid().optional(),
  assignedTo: z.string().uuid().optional(),
  deadline: z.string().optional(),
});

export type TaskCreateInput = z.infer<typeof taskCreateSchema>;

// Mirrors tasks.py's TaskReviewCreate + its _validate_outcome_fields combination rules exactly
// (re-read fresh this pass, not from memory of the earlier Employee-side pass) —
// Business_Logic_Security_Cheat_Sheet.md "Validate Combinations", already applied server-side;
// FRONTEND_ARCHITECTURE.md §7 says the client Zod schema mirrors the request body field-for-field,
// which for this endpoint means mirroring the *combination* rule too, not just per-field bounds —
// otherwise the client would accept a shape the server always 422s, a confusing UX gap.
export const taskReviewSchema = z
  .object({
    outcome: z.enum(["approved", "reassigned", "billing"]),
    notes: z.string().max(2000, "Notes are too long").optional(),
    remainingWorkDescription: z.string().max(2000, "Description is too long").optional(),
    assignedTo: z.string().uuid().optional(),
    billingDeadline: z.string().optional(),
    billingDescription: z.string().max(5000, "Description is too long").optional(),
    billingAmount: z.number().gt(0, "Amount must be greater than 0").optional(),
    billingRecipient: z.string().max(200, "Recipient is too long").optional(),
  })
  .superRefine((val, ctx) => {
    const billingFieldsSet =
      val.billingDeadline !== undefined ||
      val.billingDescription !== undefined ||
      val.billingAmount !== undefined ||
      val.billingRecipient !== undefined;

    if (val.outcome === "reassigned") {
      if (!val.remainingWorkDescription) {
        ctx.addIssue({
          code: "custom",
          path: ["remainingWorkDescription"],
          message: "Remaining work description is required when reassigning",
        });
      }
      if (billingFieldsSet) {
        ctx.addIssue({ code: "custom", path: ["outcome"], message: "Billing fields are only valid for outcome=billing" });
      }
    } else if (val.outcome === "billing") {
      if (
        !val.assignedTo ||
        !val.billingDeadline ||
        !val.billingDescription ||
        !val.billingAmount ||
        !val.billingRecipient
      ) {
        ctx.addIssue({
          code: "custom",
          path: ["outcome"],
          message:
            "assignedTo, billingDeadline, billingDescription, billingAmount, and billingRecipient are all required for outcome=billing",
        });
      }
      if (val.remainingWorkDescription) {
        ctx.addIssue({
          code: "custom",
          path: ["remainingWorkDescription"],
          message: "Remaining work description is only valid for outcome=reassigned",
        });
      }
    } else {
      // approved
      if (val.remainingWorkDescription || val.assignedTo || billingFieldsSet) {
        ctx.addIssue({ code: "custom", path: ["outcome"], message: "Only notes is valid for outcome=approved" });
      }
    }
  });

export type TaskReviewInput = z.infer<typeof taskReviewSchema>;

// Mirrors backend/app/api/routes/issues.py's IssueResolveRequest + its _validate_resolution_fields
// combination rules exactly (re-read fresh this pass) — same FRONTEND_ARCHITECTURE.md §7 mirroring
// convention as taskReviewSchema above. Unlike TaskReviewCreate's optional `notes`,
// IssueResolveRequest.resolution_notes has no default (`Field(min_length=1, max_length=2000)`) —
// always required regardless of resolution_type, confirmed by reading the backend model directly
// rather than assuming it follows taskReviewSchema's own shape.
export const issueResolveSchema = z
  .object({
    resolutionType: z.enum(["clarified", "deadline_adjusted", "reassigned"]),
    resolutionNotes: z.string().min(1, "Notes are required").max(2000, "Notes are too long"),
    newDeadline: z.string().optional(),
    assignedTo: z.string().uuid().optional(),
    remainingWorkDescription: z.string().max(2000, "Description is too long").optional(),
  })
  .superRefine((val, ctx) => {
    if (val.resolutionType === "deadline_adjusted") {
      if (!val.newDeadline) {
        ctx.addIssue({
          code: "custom",
          path: ["newDeadline"],
          message: "A new deadline is required when adjusting the deadline",
        });
      }
      if (val.assignedTo || val.remainingWorkDescription) {
        ctx.addIssue({
          code: "custom",
          path: ["resolutionType"],
          message: "assignedTo/remainingWorkDescription are only valid for resolutionType=reassigned",
        });
      }
    } else if (val.resolutionType === "reassigned") {
      if (!val.remainingWorkDescription) {
        ctx.addIssue({
          code: "custom",
          path: ["remainingWorkDescription"],
          message: "Remaining work description is required when reassigning",
        });
      }
      if (val.newDeadline) {
        ctx.addIssue({
          code: "custom",
          path: ["newDeadline"],
          message: "newDeadline is only valid for resolutionType=deadline_adjusted",
        });
      }
    } else {
      // clarified
      if (val.newDeadline || val.assignedTo || val.remainingWorkDescription) {
        ctx.addIssue({
          code: "custom",
          path: ["resolutionType"],
          message: "Only notes is valid for resolutionType=clarified",
        });
      }
    }
  });

export type IssueResolveInput = z.infer<typeof issueResolveSchema>;

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
