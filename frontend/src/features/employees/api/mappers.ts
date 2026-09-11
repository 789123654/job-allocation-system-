import type { Employee, EmployeeCreated } from "@/features/employees/types";

// backend/app/api/routes/employees.py's EmployeeOut/EmployeeCreated — snake_case on the wire.
// Pure, dependency-free mapping functions: no import of api-client.ts/supabase-client.ts, unlike
// get-employees.ts/create-employee.ts (which need apiRequest and so transitively pull in the
// Supabase client's module-load-time session recovery — that touches `window` via the Tauri
// store, which crashes under contract-tests' plain Node environment). Split out specifically so
// contract-tests/employees.contract.test.ts can import the REAL mappers without dragging that in.
export interface EmployeeOutDto {
  id: string;
  full_name: string;
  email: string;
  is_active: boolean;
}

export function toEmployee(dto: EmployeeOutDto): Employee {
  return { id: dto.id, fullName: dto.full_name, email: dto.email, isActive: dto.is_active };
}

export interface EmployeeCreatedDto {
  id: string;
  full_name: string;
  email: string;
  generated_password: string;
}

export function toEmployeeCreated(dto: EmployeeCreatedDto): EmployeeCreated {
  return {
    id: dto.id,
    fullName: dto.full_name,
    email: dto.email,
    isActive: true,
    generatedPassword: dto.generated_password,
  };
}
