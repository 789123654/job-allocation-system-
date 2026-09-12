import type { Issue, Task } from "@/features/tasks/types";

// backend/app/api/routes/tasks.py's TaskOut/IssueOut — snake_case on the wire. Pure,
// dependency-free mapping functions: no import of api-client.ts/supabase-client.ts, same reasoning
// as employees/api/mappers.ts and job-types/api/mappers.ts (importable from a future contract
// test without dragging in the Supabase client's module-load-time `window` access).
export interface TaskOutDto {
  id: string;
  job_type_id: string | null;
  task_type: string;
  parent_task_id: string | null;
  title: string;
  description: string | null;
  assigned_to: string | null;
  deadline: string | null;
  status: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  last_reassignment_notes: string | null;
  last_reassignment_remaining_work: string | null;
  last_reassignment_source: string | null;
  last_reassignment_at: string | null;
  billing_amount: number | null;
  billing_recipient: string | null;
}

export function toTask(dto: TaskOutDto): Task {
  return {
    id: dto.id,
    jobTypeId: dto.job_type_id,
    taskType: dto.task_type,
    parentTaskId: dto.parent_task_id,
    title: dto.title,
    description: dto.description,
    assignedTo: dto.assigned_to,
    deadline: dto.deadline,
    status: dto.status as Task["status"],
    createdBy: dto.created_by,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
    lastReassignmentNotes: dto.last_reassignment_notes,
    lastReassignmentRemainingWork: dto.last_reassignment_remaining_work,
    lastReassignmentSource: dto.last_reassignment_source,
    lastReassignmentAt: dto.last_reassignment_at,
    billingAmount: dto.billing_amount,
    billingRecipient: dto.billing_recipient,
  };
}

export interface IssueOutDto {
  id: string;
  task_id: string;
  raised_by: string;
  description: string;
  status: string;
  resolution_type: string | null;
  resolution_notes: string | null;
  remaining_work_description: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  created_at: string;
}

export function toIssue(dto: IssueOutDto): Issue {
  return {
    id: dto.id,
    taskId: dto.task_id,
    raisedBy: dto.raised_by,
    description: dto.description,
    status: dto.status,
    resolutionType: dto.resolution_type,
    resolutionNotes: dto.resolution_notes,
    remainingWorkDescription: dto.remaining_work_description,
    resolvedBy: dto.resolved_by,
    resolvedAt: dto.resolved_at,
    createdAt: dto.created_at,
  };
}
