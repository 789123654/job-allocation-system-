import { Button } from "@/components/ui/button";
import { useJobTypes } from "@/features/job-types/api/get-job-types";
import { useUpdateJobType } from "@/features/job-types/api/update-job-type";
import { useSession } from "@/stores/session-store";

export function JobTypeList() {
  const { data: jobTypes, isPending, isError } = useJobTypes();
  const { firmId, isLoading: isSessionLoading } = useSession();
  const updateJobType = useUpdateJobType();

  // Same firmId-null guard as employee-list.tsx (found during the Employees-slice security
  // audit) — without this, an authenticated user with a malformed/stale JWT missing
  // app_metadata.firm_id would see an infinite "Loading…" spinner instead of an error.
  if (!isSessionLoading && firmId === null) {
    return (
      <p className="text-sm text-(--color-ledger-danger)">
        Could not determine your firm — try signing out and back in.
      </p>
    );
  }

  if (isPending) return <p className="text-sm text-(--color-ledger-text-muted)">Loading…</p>;
  if (isError) {
    return (
      <p className="text-sm text-(--color-ledger-danger)">
        Could not load job types — try again.
      </p>
    );
  }
  if (jobTypes.length === 0) {
    return <p className="text-sm text-(--color-ledger-text-muted)">No job types yet.</p>;
  }

  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-(--color-ledger-border) text-left text-(--color-ledger-text-muted)">
          <th className="py-2 font-medium">Name</th>
          <th className="py-2 font-medium">Status</th>
          <th className="py-2 font-medium">
            <span className="sr-only">Actions</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {jobTypes.map((jobType) => (
          <tr key={jobType.id} className="border-b border-(--color-ledger-border)">
            <td className="py-2">{jobType.name}</td>
            <td className="py-2">{jobType.isActive ? "Active" : "Deactivated"}</td>
            <td className="py-2">
              <div className="flex justify-end">
                <Button
                  type="button"
                  variant="ghost"
                  disabled={updateJobType.isPending}
                  onClick={() =>
                    updateJobType.mutate({ id: jobType.id, isActive: !jobType.isActive })
                  }
                >
                  {jobType.isActive ? "Deactivate" : "Reactivate"}
                </Button>
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
