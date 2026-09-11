import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import type { Employee } from "@/features/employees/types";

// backend/app/api/routes/employees.py's EmployeeOut — snake_case on the wire.
interface EmployeeOutDto {
  id: string;
  full_name: string;
  email: string;
  is_active: boolean;
}

function toEmployee(dto: EmployeeOutDto): Employee {
  return { id: dto.id, fullName: dto.full_name, email: dto.email, isActive: dto.is_active };
}

export const employeesQueryKey = ["employees"] as const;

// API_SPEC.md §3: GET /employees, Owner only, offset/limit pagination (§1). Phase 1 scale (2-4
// firms / ~30 users, ca-tool-project-scope memory) never approaches the default page's 20-row
// limit for one firm's employee list, so no pagination UI yet — YAGNI, add when a firm's employee
// count is actually observed to exceed it.
function getEmployees(): Promise<Employee[]> {
  return apiRequest<EmployeeOutDto[]>("/employees").then((dtos) => dtos.map(toEmployee));
}

export function useEmployees() {
  return useQuery({ queryKey: employeesQueryKey, queryFn: getEmployees });
}
