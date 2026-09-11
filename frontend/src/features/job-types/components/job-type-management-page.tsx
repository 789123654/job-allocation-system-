import { CreateJobTypeDialog } from "@/features/job-types/components/create-job-type-dialog";
import { JobTypeList } from "@/features/job-types/components/job-type-list";

// FRONTEND_ARCHITECTURE.md §1: "Job Type Template Management" — Owner only.
export function JobTypeManagementPage() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl">Job types</h1>
        <CreateJobTypeDialog />
      </div>
      <JobTypeList />
    </div>
  );
}
