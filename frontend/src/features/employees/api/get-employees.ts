import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { toEmployee, type EmployeeOutDto } from "@/features/employees/api/mappers";
import type { Employee } from "@/features/employees/types";

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
