import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useEmployees } from "@/features/employees/api/get-employees";
import { useUpdateEmployee } from "@/features/employees/api/update-employee";
import { ResetPasswordDialog } from "@/features/employees/components/reset-password-dialog";
import type { Employee } from "@/features/employees/types";

export function EmployeeList() {
  // TanStack Query v5: isPending (not isLoading, which is now isPending && isFetching — verified
  // against tanstack.com's own v5 migration guide) is the "no data yet" first-render flag.
  const { data: employees, isPending, isError } = useEmployees();
  const updateEmployee = useUpdateEmployee();
  const [resetTarget, setResetTarget] = useState<Employee | null>(null);

  if (isPending) return <p className="text-sm text-(--color-ledger-text-muted)">Loading…</p>;
  if (isError) {
    return (
      <p className="text-sm text-(--color-ledger-danger)">
        Could not load employees — try again.
      </p>
    );
  }
  if (employees.length === 0) {
    return <p className="text-sm text-(--color-ledger-text-muted)">No employees yet.</p>;
  }

  return (
    <>
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-(--color-ledger-border) text-left text-(--color-ledger-text-muted)">
            <th className="py-2 font-medium">Name</th>
            <th className="py-2 font-medium">Email</th>
            <th className="py-2 font-medium">Status</th>
            <th className="py-2 font-medium">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {employees.map((employee) => (
            <tr key={employee.id} className="border-b border-(--color-ledger-border)">
              <td className="py-2">{employee.fullName}</td>
              <td className="py-2">{employee.email}</td>
              <td className="py-2">{employee.isActive ? "Active" : "Deactivated"}</td>
              <td className="py-2">
                <div className="flex justify-end gap-2">
                  <Button type="button" variant="ghost" onClick={() => setResetTarget(employee)}>
                    Reset password
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={updateEmployee.isPending}
                    onClick={() =>
                      updateEmployee.mutate({ id: employee.id, isActive: !employee.isActive })
                    }
                  >
                    {employee.isActive ? "Deactivate" : "Reactivate"}
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {resetTarget && (
        <ResetPasswordDialog
          employeeId={resetTarget.id}
          employeeName={resetTarget.fullName}
          open
          onOpenChange={(next) => {
            if (!next) setResetTarget(null);
          }}
        />
      )}
    </>
  );
}
