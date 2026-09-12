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

// Mirrors crud.list_employees' real join against `tasks` (pending_job_count = assigned/
// in_progress) rather than a hardcoded fixture number, so a test that seeds different tasks for
// "e1" sees the count actually change — computed at request time, not module-load time, since
// `tasks` is reset independently per test.
function pendingJobCount(employeeId: string): number {
  return tasks.filter(
    (t) => t.assigned_to === employeeId && (t.status === "assigned" || t.status === "in_progress"),
  ).length;
}

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

interface IssueRecord {
  id: string;
  task_id: string;
  raised_by: string;
  description: string;
  status: string;
  resolution_type: string | null;
  resolution_notes: string | null;
  remaining_work_description: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  created_at: string;
}

let issues: IssueRecord[] = [];

export function resetIssuesFixture(): void {
  issues = [
    {
      id: "i1",
      task_id: "t1",
      raised_by: EMPLOYEE_ID,
      description: "Client hasn't sent the required documents",
      status: "open",
      resolution_type: null,
      resolution_notes: null,
      remaining_work_description: null,
      resolved_by: null,
      resolved_at: null,
      created_at: NOW,
    },
  ];
}
resetIssuesFixture();

interface NotificationRecord {
  id: string;
  type: string;
  task_id: string | null;
  issue_id: string | null;
  is_read: boolean;
  created_at: string;
}

let notifications: NotificationRecord[] = [];

export function resetNotificationsFixture(): void {
  notifications = [
    { id: "n1", type: "issue_raised", task_id: "t1", issue_id: "i1", is_read: false, created_at: NOW },
  ];
}
resetNotificationsFixture();

export const handlers = [
  http.post(`${SUPABASE_URL}/auth/v1/token`, () => HttpResponse.json(fakeSession)),
  http.put(`${SUPABASE_URL}/auth/v1/user`, () => HttpResponse.json(fakeUser)),

  // API_SPEC.md §3 Employees — mirrors backend/app/api/routes/employees.py's actual shapes.
  http.get(`${API_BASE_URL}/employees`, () =>
    HttpResponse.json(
      employees.map((e) => ({ ...e, pending_job_count: pendingJobCount(e.id) })),
    ),
  ),
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

  // tasks.py — mirrors the real route shapes. Query filters applied unconditionally here (the
  // fixture has no concept of role) — Employee-side tests never send any, so this is a no-op for
  // them; Dashboard tests do, mirroring crud.list_tasks' real Owner-only filter behavior.
  http.get(`${API_BASE_URL}/tasks`, ({ request }) => {
    const url = new URL(request.url);
    let filtered = tasks;
    const status = url.searchParams.get("status");
    const assignedTo = url.searchParams.get("assigned_to");
    const jobTypeId = url.searchParams.get("job_type_id");
    const taskType = url.searchParams.get("task_type");
    if (status) filtered = filtered.filter((t) => t.status === status);
    if (assignedTo) filtered = filtered.filter((t) => t.assigned_to === assignedTo);
    if (jobTypeId) filtered = filtered.filter((t) => t.job_type_id === jobTypeId);
    if (taskType) filtered = filtered.filter((t) => t.task_type === taskType);
    return HttpResponse.json(filtered);
  }),
  http.post(`${API_BASE_URL}/tasks`, async ({ request }) => {
    const body = (await request.json()) as {
      title: string;
      description: string | null;
      job_type_id: string | null;
      assigned_to: string | null;
      deadline: string | null;
    };
    const created = makeTask({
      id: crypto.randomUUID(),
      title: body.title,
      description: body.description,
      job_type_id: body.job_type_id,
      assigned_to: body.assigned_to,
      deadline: body.deadline,
      status: body.assigned_to ? "assigned" : "created",
    });
    tasks.push(created);
    return HttpResponse.json(created, { status: 201 });
  }),
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
  http.post(`${API_BASE_URL}/tasks/:id/review`, async ({ params, request }) => {
    const task = tasks.find((t) => t.id === params.id);
    if (!task) return new HttpResponse(null, { status: 404 });
    if (task.status !== "submitted") {
      return HttpResponse.json(
        {
          type: "about:blank",
          title: "Conflict",
          status: 409,
          detail: "Task cannot be reviewed from its current status",
          instance: "",
        },
        { status: 409 },
      );
    }
    const body = (await request.json()) as {
      outcome: "approved" | "reassigned" | "billing";
      notes: string | null;
      remaining_work_description: string | null;
      assigned_to: string | null;
      billing_amount: number | null;
      billing_recipient: string | null;
    };
    if (body.outcome === "approved") {
      task.status = "completed";
    } else if (body.outcome === "reassigned") {
      task.status = "in_progress";
      task.last_reassignment_notes = body.notes;
      task.last_reassignment_remaining_work = body.remaining_work_description;
      task.last_reassignment_source = "review";
      task.last_reassignment_at = NOW;
      if (body.assigned_to) task.assigned_to = body.assigned_to;
    } else {
      task.status = "completed";
      task.billing_amount = body.billing_amount;
      task.billing_recipient = body.billing_recipient;
    }
    return HttpResponse.json(task);
  }),
  http.get(`${API_BASE_URL}/issues/:id`, ({ params }) => {
    const issue = issues.find((i) => i.id === params.id);
    if (!issue) return new HttpResponse(null, { status: 404 });
    return HttpResponse.json(issue);
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

  // notifications.py — mirrors the real route shape. unread_only defaults true server-side; the
  // fixture's own seeded notification is already unread, so no filtering logic needed to match
  // that default for what this pass actually tests.
  http.get(`${API_BASE_URL}/notifications`, () => HttpResponse.json(notifications)),
];

export const server = setupServer(...handlers);
