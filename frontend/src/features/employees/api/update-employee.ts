import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { employeesQueryKey } from "@/features/employees/api/get-employees";
import type { Employee } from "@/features/employees/types";

interface EmployeeOutDto {
  id: string;
  full_name: string;
  email: string;
  is_active: boolean;
}

// API_SPEC.md §3: PATCH /employees/{id} — employees.py's real route takes no Idempotency-Key
// (no IdempotencyKeyHeader param on update_employee) and setting is_active twice is naturally
// idempotent (same end state either way), so no key needed here.
function updateEmployee(input: { id: string; isActive: boolean }): Promise<Employee> {
  return apiRequest<EmployeeOutDto>(`/employees/${input.id}`, {
    method: "PATCH",
    body: { is_active: input.isActive },
  }).then((dto) => ({
    id: dto.id,
    fullName: dto.full_name,
    email: dto.email,
    isActive: dto.is_active,
  }));
}

export function useUpdateEmployee() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateEmployee,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: employeesQueryKey });
    },
  });
}
