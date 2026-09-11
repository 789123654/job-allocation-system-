import { z } from "zod";

// Mirrors backend/app/api/routes/job_types.py's JobTypeCreate exactly (name: NoNulStr,
// min_length=1, max_length=200 — same bound as EmployeeCreate.full_name) —
// FRONTEND_ARCHITECTURE.md §7: the Zod schema is both the client-side validator and the TS request
// type, not maintained twice.
export const jobTypeCreateSchema = z.object({
  name: z.string().min(1, "Name is required").max(200, "Name is too long"),
});

export type JobTypeCreateInput = z.infer<typeof jobTypeCreateSchema>;

// API response shape (API_SPEC.md / job_types.py's JobTypeOut) — read data, not form input, so no
// Zod schema needed here.
export interface JobType {
  id: string;
  name: string;
  isActive: boolean;
}
