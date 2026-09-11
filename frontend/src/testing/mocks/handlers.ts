import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";

// VITE_SUPABASE_URL for the test environment (.env.test) — fake project, no real Supabase call
// ever happens in tests, every request below is intercepted.
const SUPABASE_URL = "https://test-project.supabase.co";

const fakeUser = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "owner@example.com",
  app_metadata: { firm_id: "22222222-2222-2222-2222-222222222222", role: "owner" },
};

const fakeSession = {
  access_token: "fake-access-token",
  refresh_token: "fake-refresh-token",
  expires_in: 3600,
  token_type: "bearer",
  user: fakeUser,
};

// VITE_API_BASE_URL for the test environment (.env.test) — FastAPI is never really called either.
const API_BASE_URL = "http://localhost:8000";

interface EmployeeRecord {
  id: string;
  full_name: string;
  email: string;
  is_active: boolean;
}

let employees: EmployeeRecord[] = [];

// Called from each employees-feature test's beforeEach — server.resetHandlers() (setup-tests.ts)
// only undoes server.use() overrides, not this closure's own state.
export function resetEmployeesFixture(): void {
  employees = [{ id: "e1", full_name: "Alex Employee", email: "alex@example.com", is_active: true }];
}
resetEmployeesFixture();

interface JobTypeRecord {
  id: string;
  name: string;
  is_active: boolean;
}

let jobTypes: JobTypeRecord[] = [];

export function resetJobTypesFixture(): void {
  jobTypes = [{ id: "jt1", name: "Tax Audit", is_active: true }];
}
resetJobTypesFixture();

export const handlers = [
  http.post(`${SUPABASE_URL}/auth/v1/token`, () => HttpResponse.json(fakeSession)),
  http.put(`${SUPABASE_URL}/auth/v1/user`, () => HttpResponse.json(fakeUser)),

  // API_SPEC.md §3 Employees — mirrors backend/app/api/routes/employees.py's actual shapes.
  http.get(`${API_BASE_URL}/employees`, () => HttpResponse.json(employees)),
  http.post(`${API_BASE_URL}/employees`, async ({ request }) => {
    const body = (await request.json()) as { full_name: string; email: string };
    if (employees.some((e) => e.email === body.email)) {
      return HttpResponse.json(
        {
          type: "about:blank",
          title: "Conflict",
          status: 409,
          detail: "Email already in use",
          instance: "",
        },
        { status: 409 },
      );
    }
    const created: EmployeeRecord = {
      id: crypto.randomUUID(),
      full_name: body.full_name,
      email: body.email,
      is_active: true,
    };
    employees.push(created);
    return HttpResponse.json({ ...created, generated_password: "TempPass123!" }, { status: 201 });
  }),
  http.patch(`${API_BASE_URL}/employees/:id`, async ({ params, request }) => {
    const employee = employees.find((e) => e.id === params.id);
    if (!employee) return new HttpResponse(null, { status: 404 });
    const body = (await request.json()) as { is_active: boolean };
    employee.is_active = body.is_active;
    return HttpResponse.json(employee);
  }),
  http.post(`${API_BASE_URL}/employees/:id/reset-password`, ({ params }) => {
    const employee = employees.find((e) => e.id === params.id);
    if (!employee) return new HttpResponse(null, { status: 404 });
    return HttpResponse.json({ generated_password: "NewTempPass456!" });
  }),

  // job_types.py — mirrors the real route shapes.
  http.get(`${API_BASE_URL}/job-types`, () => HttpResponse.json(jobTypes)),
  http.post(`${API_BASE_URL}/job-types`, async ({ request }) => {
    const body = (await request.json()) as { name: string };
    if (jobTypes.some((jt) => jt.name === body.name)) {
      return HttpResponse.json(
        {
          type: "about:blank",
          title: "Conflict",
          status: 409,
          detail: "Job type name already in use",
          instance: "",
        },
        { status: 409 },
      );
    }
    const created: JobTypeRecord = { id: crypto.randomUUID(), name: body.name, is_active: true };
    jobTypes.push(created);
    return HttpResponse.json(created, { status: 201 });
  }),
  http.patch(`${API_BASE_URL}/job-types/:id`, async ({ params, request }) => {
    const jobType = jobTypes.find((jt) => jt.id === params.id);
    if (!jobType) return new HttpResponse(null, { status: 404 });
    const body = (await request.json()) as { is_active: boolean };
    jobType.is_active = body.is_active;
    return HttpResponse.json(jobType);
  }),
];

export const server = setupServer(...handlers);
