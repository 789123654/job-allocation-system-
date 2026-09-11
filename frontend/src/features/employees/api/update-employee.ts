import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { employeesQueryKey } from "@/features/employees/api/get-employees";
import { toEmployee, type EmployeeOutDto } from "@/features/employees/api/mappers";
import type { Employee } from "@/features/employees/types";

// API_SPEC.md §3: PATCH /employees/{id} — employees.py's real route takes no Idempotency-Key
// (no IdempotencyKeyHeader param on update_employee) and setting is_active twice is naturally
// idempotent (same end state either way), so no key needed here. Same EmployeeOut response shape
// as GET /employees — reuses get-employees.ts's mapper instead of a second copy of it.
function updateEmployee(input: { id: string; isActive: boolean }): Promise<Employee> {
  return apiRequest<EmployeeOutDto>(`/employees/${input.id}`, {
    method: "PATCH",
    body: { is_active: input.isActive },
  }).then(toEmployee);
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
