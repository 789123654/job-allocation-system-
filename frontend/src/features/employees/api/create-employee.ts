import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { employeesQueryKeyPrefix } from "@/features/employees/api/get-employees";
import { toEmployeeCreated, type EmployeeCreatedDto } from "@/features/employees/api/mappers";
import type { EmployeeCreated, EmployeeCreateInput } from "@/features/employees/types";

// API_SPEC.md §3: POST /employees dedups via email's own uniqueness (Supabase auth.users), not an
// Idempotency-Key header — a retry with the same email gets 409 (employees.py already maps that
// to "Email already in use" server-side, in ApiError.problem.detail). No idempotencyKey passed
// here, matching the real route (no IdempotencyKeyHeader param on create_employee).
function createEmployee(input: EmployeeCreateInput): Promise<EmployeeCreated> {
  return apiRequest<EmployeeCreatedDto>("/employees", {
    method: "POST",
    body: { full_name: input.fullName, email: input.email },
  }).then(toEmployeeCreated);
}

export function useCreateEmployee() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createEmployee,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: employeesQueryKeyPrefix });
    },
  });
}
