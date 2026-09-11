import { useMutation } from "@tanstack/react-query";
import { apiRequest, ApiError } from "@/lib/api-client";

// API_SPEC.md §3 / employees.py's reset_password route: real Idempotency-Key required. The caller
// (reset-password-dialog.tsx) generates the key once per dialog-open attempt and passes it in on
// every call for that attempt — lib/api-client.ts's fix (2026-09-11) means the SAME key here
// actually reaches the server unchanged, satisfying rest-api-guidelines Rule 230's retry guarantee
// instead of a fresh key defeating it.
function resetEmployeePassword(input: {
  employeeId: string;
  idempotencyKey: string;
}): Promise<string> {
  return apiRequest<{ generated_password: string }>(
    `/employees/${input.employeeId}/reset-password`,
    { method: "POST", idempotencyKey: input.idempotencyKey },
  ).then((dto) => dto.generated_password);
}

export function useResetEmployeePassword() {
  return useMutation({ mutationFn: resetEmployeePassword });
}

// employees.py: a genuine concurrent retry that loses the idempotency-key insert race gets a 409
// with an explanatory message, not a replayed password (the endpoint's own documented deviation
// from replaying the exact response — API_SPEC.md §3's note on this route). Exported so the
// dialog can show that 409 as "already reset, ask the employee to check with you" rather than a
// generic error.
export function isAlreadyResetConflict(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}
