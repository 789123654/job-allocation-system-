import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { employeesQueryKey } from "@/features/employees/api/get-employees";
import type { EmployeeCreated, EmployeeCreateInput } from "@/features/employees/types";

interface EmployeeCreatedDto {
  id: string;
  full_name: string;
  email: string;
  generated_password: string;
}

// API_SPEC.md §3: POST /employees dedups via email's own uniqueness (Supabase auth.users), not an
// Idempotency-Key header — a retry with the same email gets 409 (employees.py already maps that
// to "Email already in use" server-side, in ApiError.problem.detail). No idempotencyKey passed
// here, matching the real route (no IdempotencyKeyHeader param on create_employee).
function createEmployee(input: EmployeeCreateInput): Promise<EmployeeCreated> {
  return apiRequest<EmployeeCreatedDto>("/employees", {
    method: "POST",
    body: { full_name: input.fullName, email: input.email },
  }).then((dto) => ({
    id: dto.id,
    fullName: dto.full_name,
    email: dto.email,
    isActive: true,
    generatedPassword: dto.generated_password,
  }));
}

export function useCreateEmployee() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createEmployee,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: employeesQueryKey });
    },
  });
}
