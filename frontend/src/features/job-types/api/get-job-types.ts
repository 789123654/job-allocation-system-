import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api-client";
import { tenantQueryKey, tenantQueryKeyPrefix } from "@/lib/tenant-query-key";
import { toJobType, type JobTypeOutDto } from "@/features/job-types/api/mappers";
import type { JobType } from "@/features/job-types/types";
import { useSession } from "@/stores/session-store";

export const jobTypesQueryKeyPrefix = tenantQueryKeyPrefix("job-types");

// API_SPEC.md / job_types.py: GET /job-types, offset/limit pagination, same YAGNI reasoning as
// get-employees.ts — Phase 1 scale (2-4 firms) never approaches the default page's 20-row limit,
// so no pagination UI yet.
function getJobTypes(): Promise<JobType[]> {
  return apiRequest<JobTypeOutDto[]>("/job-types").then((dtos) => dtos.map(toJobType));
}

export function useJobTypes() {
  const { firmId } = useSession();
  return useQuery({
    queryKey: tenantQueryKey("job-types", firmId),
    queryFn: getJobTypes,
    enabled: firmId !== null,
  });
}
