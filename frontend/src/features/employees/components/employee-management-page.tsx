import { CreateEmployeeDialog } from "@/features/employees/components/create-employee-dialog";
import { EmployeeList } from "@/features/employees/components/employee-list";

// FRONTEND_ARCHITECTURE.md §1: "Employee Management (list, deactivate)" — Owner only. Create and
// reset-password are also here since this is the one screen for the whole Employees resource and
// API_SPEC.md documents both as real Owner actions on it (POST /employees, POST
// /employees/{id}/reset-password) with no other screen named for them.
export function EmployeeManagementPage() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl">Employees</h1>
        <CreateEmployeeDialog />
      </div>
      <EmployeeList />
    </div>
  );
}
