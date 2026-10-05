import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OwnerTaskReviewPage } from "@/features/tasks/components/owner-task-review-page";
import { server } from "@/testing/mocks/handlers";
import { useSession } from "@/stores/session-store";

vi.mock("@/stores/session-store", () => ({ useSession: vi.fn() }));

const API_BASE_URL = "http://localhost:8000";

// Valid RFC 4122 v4 UUIDs (variant nibble 8/9/a/b) so schema checks on ids pass.
const TASK_ID = "5b6f2a3e-1c2d-4e5f-8a9b-0c1d2e3f4a5b";
const ALEX_ID = "6c7d8e9f-0a1b-4c2d-8e3f-4a5b6c7d8e9f";
const CAROL_INACTIVE_ID = "8e9f0a1b-2c3d-4e4f-8a5b-6c7d8e9f0a1b";

const NOW = "2026-09-01T00:00:00Z";

const EMPLOYEES = [
  {
    id: ALEX_ID,
    full_name: "Alex Employee",
    email: "alex@example.com",
    is_active: true,
    pending_job_count: 0,
  },
  {
    id: CAROL_INACTIVE_ID,
    full_name: "Carol Inactive",
    email: "carol@example.com",
    is_active: false,
    pending_job_count: 0,
  },
];

// Same option shape the existing owner page test passes to the page.
const EMPLOYEE_OPTIONS = [{ id: ALEX_ID, label: "Alex Employee" }];

// Full employee list with active flags, passed by the route wrapper (amendment 1 of the page contract).
const PAGE_EMPLOYEES = [
  { id: ALEX_ID, fullName: "Alex Employee", isActive: true },
  { id: CAROL_INACTIVE_ID, fullName: "Carol Inactive", isActive: false },
];

// Wire shape mirrors the task record the existing handlers serve (snake_case).
function makeTask(status: string) {
  return {
    id: TASK_ID,
    job_type_id: null,
    task_type: "standard",
    parent_task_id: null,
    title: "Prepare GST filing",
    description: "Quarterly return",
    assigned_to: ALEX_ID,
    deadline: null,
    status,
    created_by: "owner-1",
    created_at: NOW,
    updated_at: NOW,
    last_reassignment_notes: null,
    last_reassignment_remaining_work: null,
    last_reassignment_source: null,
    last_reassignment_at: null,
    billing_amount: null,
    billing_recipient: null,
  };
}

// Overrides GET /tasks/:id for one test. Pass null to answer 404 (task cannot be loaded).
function mockTask(task: ReturnType<typeof makeTask> | null) {
  server.use(
    http.get(`${API_BASE_URL}/tasks/:id`, () =>
      task === null ? new HttpResponse(null, { status: 404 }) : HttpResponse.json(task),
    ),
  );
}

function renderPage(role: "owner" | "employee") {
  vi.mocked(useSession).mockReturnValue({
    session: null,
    role,
    firmId: "firm-1",
    mustChangePassword: false,
    isLoading: false,
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/owner-tasks/${TASK_ID}/review`]}>
        <Routes>
          <Route path="/" element={<div>OWNER-HOME</div>} />
          <Route
            path="/owner-tasks/:taskId/review"
            element={
              <OwnerTaskReviewPage employeeOptions={EMPLOYEE_OPTIONS} employees={PAGE_EMPLOYEES} />
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function editTaskButton() {
  return screen.queryByRole("button", { name: /^edit task$/i });
}

describe("OwnerTaskReviewPage: Edit task button", () => {
  beforeEach(() => {
    server.use(http.get(`${API_BASE_URL}/employees`, () => HttpResponse.json(EMPLOYEES)));
  });

  // Item 1
  it.each(["created", "assigned"])(
    "item 1: shows Edit task to an owner when the task is %s",
    async (status) => {
      mockTask(makeTask(status));
      renderPage("owner");

      expect(await screen.findByRole("button", { name: /^edit task$/i })).toBeInTheDocument();
    },
  );

  // Item 2
  it.each(["created", "assigned", "in_progress", "submitted", "completed", "billed"])(
    "item 2: does not show Edit task to an employee when the task is %s",
    async (status) => {
      mockTask(makeTask(status));
      renderPage("employee");
      await screen.findByText("Prepare GST filing");

      expect(editTaskButton()).not.toBeInTheDocument();
    },
  );

  // Item 3
  it.each(["in_progress", "submitted", "completed", "billed"])(
    "item 3: does not show Edit task to an owner when the task is %s",
    async (status) => {
      mockTask(makeTask(status));
      renderPage("owner");
      await screen.findByText("Prepare GST filing");

      expect(editTaskButton()).not.toBeInTheDocument();
    },
  );

  // Item 4
  it("item 4: opens an Edit task dialog with Title, Description and Assignee pre-filled", async () => {
    mockTask(makeTask("assigned"));
    const user = userEvent.setup();
    renderPage("owner");

    await user.click(await screen.findByRole("button", { name: /^edit task$/i }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/^edit task$/i)).toBeInTheDocument();
    expect((within(dialog).getByLabelText(/^title$/i) as HTMLInputElement).value).toBe(
      "Prepare GST filing",
    );
    expect((within(dialog).getByLabelText(/^description$/i) as HTMLInputElement).value).toBe(
      "Quarterly return",
    );
    const assignee = within(dialog).getByLabelText(/^assignee$/i);
    if (assignee instanceof HTMLSelectElement) {
      expect(assignee.value).toBe(ALEX_ID);
    } else {
      expect(assignee).toHaveTextContent(/alex employee/i);
    }
  });

  // Item 5
  it("item 5: a submitted task still shows the review form, and no Edit task button", async () => {
    mockTask(makeTask("submitted"));
    renderPage("owner");

    expect(await screen.findByRole("button", { name: /submit review/i })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /outcome/i })).toBeInTheDocument();
    expect(editTaskButton()).not.toBeInTheDocument();
  });

  // Item 6
  it("item 6: a task that cannot be loaded shows the error message and no Edit task button", async () => {
    mockTask(null);
    renderPage("owner");

    expect(await screen.findByText("Could not load this task.")).toBeInTheDocument();
    expect(editTaskButton()).not.toBeInTheDocument();
  });
});
