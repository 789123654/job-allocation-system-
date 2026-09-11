import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { jobTypesQueryKeyPrefix } from "@/features/job-types/api/get-job-types";
import { toJobType, type JobTypeOutDto } from "@/features/job-types/api/mappers";
import type { JobType } from "@/features/job-types/types";

// job_types.py's real route takes no Idempotency-Key (no IdempotencyKeyHeader param on
// update_job_type) and setting is_active twice is naturally idempotent — same reasoning as
// update-employee.ts. Reuses get-job-types.ts's mapper instead of a second copy of it.
function updateJobType(input: { id: string; isActive: boolean }): Promise<JobType> {
  return apiRequest<JobTypeOutDto>(`/job-types/${input.id}`, {
    method: "PATCH",
    body: { is_active: input.isActive },
  }).then(toJobType);
}

export function useUpdateJobType() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateJobType,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: jobTypesQueryKeyPrefix });
    },
  });
}
