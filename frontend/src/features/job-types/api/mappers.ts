import type { JobType } from "@/features/job-types/types";

// backend/app/api/routes/job_types.py's JobTypeOut — snake_case on the wire. Pure, dependency-free
// mapping function: no import of api-client.ts/supabase-client.ts, same reasoning as
// employees/api/mappers.ts (keeps this importable from a future contract test without dragging in
// the Supabase client's module-load-time `window` access, which crashes under plain Node).
export interface JobTypeOutDto {
  id: string;
  name: string;
  is_active: boolean;
}

export function toJobType(dto: JobTypeOutDto): JobType {
  return { id: dto.id, name: dto.name, isActive: dto.is_active };
}
