import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { jobTypesQueryKeyPrefix } from "@/features/job-types/api/get-job-types";
import { toJobType, type JobTypeOutDto } from "@/features/job-types/api/mappers";
import type { JobType, JobTypeCreateInput } from "@/features/job-types/types";

// job_types.py's create_job_type dedups via a DB unique constraint (name), caught as
// IntegrityError -> 409 (crud.py:294-308, checked directly — not a check-then-insert, so no
// TOCTOU race like failure mode 6's task-status bug). No IdempotencyKeyHeader param on the real
// route, same as create_employee — a retry with the same name naturally 409s instead of double-
// creating, so no idempotencyKey passed here either.
function createJobType(input: JobTypeCreateInput): Promise<JobType> {
  return apiRequest<JobTypeOutDto>("/job-types", {
    method: "POST",
    body: { name: input.name },
  }).then(toJobType);
}

export function useCreateJobType() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createJobType,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: jobTypesQueryKeyPrefix });
    },
  });
}
