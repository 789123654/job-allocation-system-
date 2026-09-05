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
  // FRONTEND_ARCHITECTURE.md §4/§5: client-generated per request, attached here (not
  // per-feature) — one place, matching the single-client-instance pattern.
  idempotent?: boolean;
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
  if (options.idempotent) {
    headers["Idempotency-Key"] = crypto.randomUUID();
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
