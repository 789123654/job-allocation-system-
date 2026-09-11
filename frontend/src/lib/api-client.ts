import { env } from "@/config/env";
import { supabase } from "@/lib/supabase-client";

// RFC 9457 problem+json — API_SPEC.md §1 Rule 176.
export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance: string;
}

export class ApiError extends Error {
  status: number;
  problem: ProblemDetails | null;

  constructor(status: number, problem: ProblemDetails | null) {
    super(problem?.detail ?? `API request failed with status ${status}`);
    this.status = status;
    this.problem = problem;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  // rest-api-guidelines Rule 230 (re-checked 2026-09-11, building the employees slice's
  // reset-password call — its first real caller): the SAME key must survive every retry of one
  // logical operation, or the server's dedup cache never matches and a retried request just
  // re-executes. Generating the key inside apiRequest() (as this used to do, fresh per HTTP call)
  // broke exactly that guarantee. The caller now owns the key's lifetime — generate it once per
  // logical attempt (e.g. `useRef`/`useState` in a mutation hook, reused across that attempt's
  // retries; a genuinely new attempt gets a new key) and pass it in here.
  idempotencyKey?: string;
}

async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(await authHeaders()),
  };
  if (options.idempotencyKey) {
    headers["Idempotency-Key"] = options.idempotencyKey;
  }

  const response = await fetch(`${env.API_BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (!response.ok) {
    const problem = (await response.json().catch(() => null)) as ProblemDetails | null;
    throw new ApiError(response.status, problem);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
