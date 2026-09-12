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

interface TaskRecord {
  id: string;
  job_type_id: string | null;
  task_type: string;
  parent_task_id: string | null;
  title: string;
  description: string | null;
  assigned_to: string | null;
  deadline: string | null;
  status: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  last_reassignment_notes: string | null;
  last_reassignment_remaining_work: string | null;
  last_reassignment_source: string | null;
  last_reassignment_at: string | null;
  billing_amount: number | null;
  billing_recipient: string | null;
}

const EMPLOYEE_ID = "e1";
const NOW = "2026-09-01T00:00:00Z";

function makeTask(overrides: Partial<TaskRecord>): TaskRecord {
  return {
    id: crypto.randomUUID(),
    job_type_id: null,
    task_type: "standard",
    parent_task_id: null,
    title: "Untitled task",
    description: null,
    assigned_to: EMPLOYEE_ID,
    deadline: null,
    status: "assigned",
    created_by: "owner-1",
    created_at: NOW,
    updated_at: NOW,
    last_reassignment_notes: null,
    last_reassignment_remaining_work: null,
    last_reassignment_source: null,
    last_reassignment_at: null,
    billing_amount: null,
    billing_recipient: null,
    ...overrides,
  };
}

let tasks: TaskRecord[] = [];

export function resetTasksFixture(): void {
  tasks = [
    makeTask({ id: "t1", title: "File GST return", status: "assigned" }),
    makeTask({ id: "t2", title: "Collect billing details", task_type: "billing", status: "assigned" }),
    makeTask({ id: "t3", title: "Already submitted", status: "submitted" }),
  ];
}
resetTasksFixture();

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

  // tasks.py — mirrors the real route shapes. No status/assigned_to/job_type_id/task_type filters
  // applied here (crud.list_tasks is role-scoped server-side, not filtered) — this fixture only
  // ever plays the Employee role in this session's tests, so it always returns every seeded task.
  http.get(`${API_BASE_URL}/tasks`, () => HttpResponse.json(tasks)),
  http.get(`${API_BASE_URL}/tasks/:id`, ({ params }) => {
    const task = tasks.find((t) => t.id === params.id);
    if (!task) return new HttpResponse(null, { status: 404 });
    return HttpResponse.json(task);
  }),
  http.post(`${API_BASE_URL}/tasks/:id/submit`, ({ params }) => {
    const task = tasks.find((t) => t.id === params.id);
    if (!task) return new HttpResponse(null, { status: 404 });
    if (task.status !== "assigned" && task.status !== "in_progress") {
      return HttpResponse.json(
        {
          type: "about:blank",
          title: "Conflict",
          status: 409,
          detail: "Task cannot be submitted from its current status",
          instance: "",
        },
        { status: 409 },
      );
    }
    task.status = "submitted";
    return HttpResponse.json(task);
  }),
  http.post(`${API_BASE_URL}/tasks/:id/mark-billed`, ({ params }) => {
    const task = tasks.find((t) => t.id === params.id);
    if (!task) return new HttpResponse(null, { status: 404 });
    if (task.task_type !== "billing" || (task.status !== "assigned" && task.status !== "in_progress")) {
      return HttpResponse.json(
        {
          type: "about:blank",
          title: "Conflict",
          status: 409,
          detail: "Task cannot be marked billed — wrong task_type or status",
          instance: "",
        },
        { status: 409 },
      );
    }
    task.status = "billed";
    return HttpResponse.json(task);
  }),
  http.post(`${API_BASE_URL}/tasks/:id/issues`, async ({ params, request }) => {
    const task = tasks.find((t) => t.id === params.id);
    if (!task) return new HttpResponse(null, { status: 404 });
    const body = (await request.json()) as { description: string };
    return HttpResponse.json(
      {
        id: crypto.randomUUID(),
        task_id: task.id,
        raised_by: EMPLOYEE_ID,
        description: body.description,
        status: "open",
        resolution_type: null,
        resolution_notes: null,
        remaining_work_description: null,
        resolved_by: null,
        resolved_at: null,
        created_at: NOW,
      },
      { status: 201 },
    );
  }),
];

export const server = setupServer(...handlers);
