import { z } from "zod";

// Mirrors backend/app/api/routes/employees.py's EmployeeCreate exactly (same field set, same
// bound) — FRONTEND_ARCHITECTURE.md §7: the Zod schema is both the client-side validator and the
// TS request type, not maintained twice.
export const employeeCreateSchema = z.object({
  fullName: z.string().min(1, "Name is required").max(200, "Name is too long"),
  email: z.string().email("Enter a valid email address"),
});

export type EmployeeCreateInput = z.infer<typeof employeeCreateSchema>;

// API response shapes (API_SPEC.md §3 Employees table / employees.py's Pydantic models) — read
// data, not form input, so no Zod schema needed for these (nothing to validate on the way in).
export interface Employee {
  id: string;
  fullName: string;
  email: string;
  isActive: boolean;
}

export interface EmployeeCreated extends Employee {
  generatedPassword: string;
}
